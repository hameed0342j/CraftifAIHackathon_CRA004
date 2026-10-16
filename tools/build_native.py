"""Build the firmware state machine for the host.

    python tools/build_native.py            # shared library for simlab + run C unit tests
    python tools/build_native.py --lib-only

Uses $CC, then cc/gcc/clang, then `python -m ziglang cc` (pip install ziglang),
so it works on Windows without a toolchain.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "firmgen" / "main" / "ll_fsm.c"
INC = ROOT / "firmgen" / "main"
TEST = ROOT / "firmgen" / "test" / "test_fsm.c"
OUT = ROOT / "build" / "native"


def compiler() -> list[str]:
    if os.environ.get("CC"):
        return os.environ["CC"].split()
    for name in ("cc", "gcc", "clang"):
        if shutil.which(name):
            return [name]
    try:
        import ziglang  # noqa: F401
    except ImportError:
        sys.exit("no C compiler found: install gcc/clang or `pip install ziglang`")
    return [sys.executable, "-m", "ziglang", "cc"]


def lib_name() -> str:
    if sys.platform == "win32":
        return "ll_fsm.dll"
    if sys.platform == "darwin":
        return "libll_fsm.dylib"
    return "libll_fsm.so"


def run(cmd: list[str]) -> None:
    print("+", " ".join(cmd))
    subprocess.run(cmd, check=True)


def build_lib(cc: list[str]) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / lib_name()
    flags = ["-std=c99", "-O2", "-Wall", "-Wextra", "-Werror", "-shared", "-DLL_BUILD_SHARED", f"-I{INC}"]
    if sys.platform != "win32":
        flags.append("-fPIC")
    run([*cc, *flags, "-o", str(out), str(SRC)])
    return out


def build_and_run_tests(cc: list[str]) -> None:
    exe = OUT / ("test_fsm.exe" if sys.platform == "win32" else "test_fsm")
    flags = ["-std=c99", "-O1", "-g", "-Wall", "-Wextra", "-Werror", f"-I{INC}"]
    run([*cc, *flags, "-o", str(exe), str(SRC), str(TEST), "-lm"] if sys.platform != "win32"
        else [*cc, *flags, "-o", str(exe), str(SRC), str(TEST)])
    run([str(exe)])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lib-only", action="store_true")
    args = ap.parse_args()
    cc = compiler()
    print("built", build_lib(cc))
    if not args.lib_only:
        build_and_run_tests(cc)


if __name__ == "__main__":
    main()
