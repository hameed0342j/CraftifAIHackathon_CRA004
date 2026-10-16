"""Export a raw camera feed (no overlays) of the simulated bathroom: a pipe joint starts
leaking, the pool grows, the valve is shut and the pool stops growing. Use it as the
video input for PipeGen (CraftifAI's tool) or for `python -m pipegen --source`.

    python tools/export_input_video.py                  # -> docs/media/sample_input.mp4 (640x480, 10 fps, 60 s)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from simlab.run import VideoSink  # noqa: E402
from simlab.scenarios import SCENARIOS  # noqa: E402
from simlab.world import World  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=ROOT / "docs" / "media" / "sample_input.mp4")
    ap.add_argument("--seconds", type=float, default=60.0)
    ap.add_argument("--close-at", type=float, default=20.0, help="shut the bathroom valve at this time")
    args = ap.parse_args()
    world = World(SCENARIOS["leak"], seed=7)
    fps = 10
    sink = VideoSink(args.out, fps, (640, 480))
    for _ in range(int(args.seconds * fps)):
        world.step(1.0 / fps)
        if world.t >= args.close_at and world.valves["bathroom-1"].target == 0.0:
            world.valves["bathroom-1"].command(True)
        frame, _ = world.render()
        sink.write(frame)
    sink.close()
    print(f"wrote {args.out} ({args.out.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
