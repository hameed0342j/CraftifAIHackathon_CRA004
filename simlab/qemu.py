"""Boot the real FirmGen image in Espressif's QEMU ESP32 ("synthetic flash").

Build once (ESP-IDF v5.5 shell):
    cd firmgen
    idf.py -B build_qemu -D SDKCONFIG=build_qemu/sdkconfig -D "SDKCONFIG_DEFAULTS=sdkconfig.defaults;sdkconfig.qemu" build
    cd build_qemu && python -m esptool --chip esp32 merge_bin --output qemu_flash_pristine.bin --fill-flash-size 4MB @flash_args
Install the emulator once:  python $IDF_PATH/tools/idf_tools.py install qemu-xtensa
"""

from __future__ import annotations

import binascii
import os
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "firmgen" / "build_qemu"


def qemu_binary() -> str:
    exe = "qemu-system-xtensa.exe" if os.name == "nt" else "qemu-system-xtensa"
    found = shutil.which(exe)
    if found:
        return found
    tools = Path.home() / ".espressif" / "tools" / "qemu-xtensa"
    cands = sorted(tools.glob(f"*/qemu/bin/{exe}"))
    if not cands:
        raise FileNotFoundError("qemu-system-xtensa not found: python $IDF_PATH/tools/idf_tools.py install qemu-xtensa")
    return str(cands[-1])


def default_efuse() -> bytes:
    """The eFuse image ESP-IDF's `idf.py qemu` uses for ESP32 (read from the installed IDF)."""
    idf = Path(os.environ.get("IDF_PATH", Path.home() / "esp" / "esp-idf-v5.5"))
    src = (idf / "tools" / "idf_py_actions" / "qemu_ext.py").read_text(encoding="utf-8")
    block = src.split("'esp32': QemuTarget(", 1)[1].split("binascii.unhexlify(", 1)[1].split(")", 1)[0]
    return binascii.unhexlify("".join(re.findall(r"'([0-9a-fA-F]+)'", block)))


class QemuEsp32:
    def __init__(self, workdir: Path, flash_image: Path = BUILD / "qemu_flash_pristine.bin") -> None:
        if not flash_image.exists():
            raise FileNotFoundError(f"{flash_image} missing: build the QEMU firmware first (see module docstring)")
        workdir.mkdir(parents=True, exist_ok=True)
        self.flash = workdir / "esp32_flash.bin"      # a fresh chip: copy of the pristine image
        shutil.copyfile(flash_image, self.flash)
        self.efuse = workdir / "esp32_efuse.bin"
        self.efuse.write_bytes(default_efuse())
        self.log_path = workdir / "esp32_serial.log"
        self._log = open(self.log_path, "ab")
        self.proc: subprocess.Popen | None = None
        self.boots = 0

    def start(self) -> None:
        """Power on (flash contents, including NVS, survive across start/stop like a real chip)."""
        args = [
            qemu_binary(), "-M", "esp32", "-m", "4M",
            "-drive", f"file={self.flash},if=mtd,format=raw",
            "-drive", f"file={self.efuse},if=none,format=raw,id=efuse",
            "-global", "driver=nvram.esp32.efuse,property=drive,value=efuse",
            "-global", "driver=timer.esp32.timg,property=wdt_disable,value=true",
            "-nic", "user,model=open_eth",
            "-nographic", "-serial", "stdio", "-monitor", "none",
        ]
        self.boots += 1
        self._log.write(f"\n===== power on #{self.boots} =====\n".encode())
        self._log.flush()
        self.proc = subprocess.Popen(args, stdout=self._log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)

    def stop(self) -> None:
        """Pull the plug."""
        if self.proc and self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait(10)
        self.proc = None
        self._log.write(b"\n===== power cut =====\n")
        self._log.flush()

    def tail(self, n: int = 8) -> list[str]:
        try:
            data = self.log_path.read_bytes()[-6000:].decode("utf-8", "replace")
        except OSError:
            return []
        clean = re.sub(r"\x1b\[[0-9;]*m", "", data)
        return [ln.rstrip() for ln in clean.splitlines() if ln.strip()][-n:]

    def close(self) -> None:
        self.stop()
        self._log.close()
