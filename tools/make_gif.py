"""Turn a simulator video into a small README GIF.

    python tools/make_gif.py runs/leak/demo.mp4 docs/media/leak.gif --every 4 --width 800
"""

from __future__ import annotations

import argparse
from pathlib import Path

import cv2
from PIL import Image


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("gif")
    ap.add_argument("--every", type=int, default=4, help="keep every Nth frame")
    ap.add_argument("--width", type=int, default=800)
    ap.add_argument("--fps", type=float, default=10)
    ap.add_argument("--max-frames", type=int, default=400)
    args = ap.parse_args()
    cap = cv2.VideoCapture(args.video)
    frames, i = [], 0
    while len(frames) < args.max_frames:
        ok, f = cap.read()
        if not ok:
            break
        if i % args.every == 0:
            h = int(f.shape[0] * args.width / f.shape[1])
            f = cv2.resize(f, (args.width, h), interpolation=cv2.INTER_AREA)
            frames.append(Image.fromarray(cv2.cvtColor(f, cv2.COLOR_BGR2RGB)).quantize(colors=96, dither=0))
        i += 1
    Path(args.gif).parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(args.gif, save_all=True, append_images=frames[1:], duration=int(1000 / args.fps), loop=0,
                   optimize=True)
    print(f"{len(frames)} frames -> {args.gif} ({Path(args.gif).stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
