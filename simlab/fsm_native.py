"""ctypes binding to firmgen/main/ll_fsm.c: the simulator runs the exact state
machine that is flashed onto the ESP32, not a Python re-implementation."""

from __future__ import annotations

import ctypes as C
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIB_DIR = ROOT / "build" / "native"
LIB_NAME = {"win32": "ll_fsm.dll", "darwin": "libll_fsm.dylib"}.get(sys.platform, "libll_fsm.so")

STATES = ["IDLE", "SUSPECT", "CONFIRMING", "CLOSED", "VERIFYING", "LATCHED", "FAULT"]
KINDS = {"detect": 0, "update": 1, "clear": 2}
CMD_RESET, CMD_CLOSE = 0, 1

ACT_VALVE_CLOSE = 1 << 0
ACT_VALVE_OPEN = 1 << 1
ACT_PUBLISH_STATE = 1 << 2
ACT_RECEIPT = 1 << 3
ACT_ALARM_ON = 1 << 4
ACT_ALARM_OFF = 1 << 5
ACT_PERSIST = 1 << 6

f32, u32 = C.c_float, C.c_uint32


class Config(C.Structure):
    _fields_ = [
        ("min_confidence", f32), ("min_pool_area_m2", f32), ("growth_close_min", f32), ("growth_stop_max", f32),
        ("suspect_timeout_ms", u32), ("confirm_hold_ms", u32), ("vision_fresh_ms", u32),
        ("confirm_timeout_ms", u32), ("travel_ms", u32), ("close_timeout_ms", u32), ("close_retries", u32),
        ("verify_window_ms", u32), ("verify_stop_hold_ms", u32), ("failsafe_wet_ms", u32),
        ("vision_only_area_m2", f32), ("vision_only_growth", f32), ("vision_only_hold_ms", u32),
        ("rearm_area_factor", f32), ("rearm_area_min_m2", f32),
    ]


class Transition(C.Structure):
    _fields_ = [
        ("seq", u32), ("from_", u32), ("to", u32), ("t_ms", u32), ("confidence", f32), ("pool_area", f32),
        ("growth_rate", f32), ("wet", u32), ("limit_switch", u32), ("mech_verified", u32),
        ("mech_verified_after_ms", u32), ("hydro_verified", u32), ("close_attempts", u32),
        ("growth_after_close", f32), ("reason", C.c_char * 32), ("trigger_event_id", C.c_char * 40),
        ("last_event_id", C.c_char * 40),
    ]


_lib = None


def lib() -> C.CDLL:
    global _lib
    if _lib is not None:
        return _lib
    path = LIB_DIR / LIB_NAME
    src = ROOT / "firmgen" / "main" / "ll_fsm.c"
    if not path.exists() or path.stat().st_mtime < src.stat().st_mtime:
        subprocess.run([sys.executable, str(ROOT / "tools" / "build_native.py"), "--lib-only"], check=True)
    L = C.CDLL(str(path))
    vp, cp = C.c_void_p, C.c_char_p
    sig = {
        "ll_config_default": (None, [C.POINTER(Config)]),
        "ll_fsm_init": (None, [vp, C.POINTER(Config), cp, u32]),
        "ll_fsm_restore": (None, [vp, C.c_int, u32]),
        "ll_fsm_on_vision": (C.c_int, [vp, cp, cp, cp, C.c_int, f32, f32, f32, u32]),
        "ll_fsm_on_wetness": (None, [vp, C.c_bool, u32]),
        "ll_fsm_on_limit": (None, [vp, C.c_bool, u32]),
        "ll_fsm_on_command": (None, [vp, C.c_int, u32]),
        "ll_fsm_tick": (None, [vp, u32]),
        "ll_fsm_take_actions": (u32, [vp]),
        "ll_fsm_pop_transition": (C.c_bool, [vp, C.POINTER(Transition)]),
        "ll_fsm_state": (C.c_int, [vp]),
        "ll_fsm_reason": (cp, [vp]),
        "ll_fsm_trigger_event_id": (cp, [vp]),
        "ll_fsm_incident_id": (cp, [vp]),
        "ll_fsm_counter": (u32, [vp, C.c_int]),
        "ll_verdict_name": (cp, [C.c_int]),
        "ll_fsm_sizeof": (C.c_size_t, []),
        "ll_config_sizeof": (C.c_size_t, []),
        "ll_transition_sizeof": (C.c_size_t, []),
    }
    for name, (res, args) in sig.items():
        fn = getattr(L, name)
        fn.restype, fn.argtypes = res, args
    if L.ll_config_sizeof() != C.sizeof(Config) or L.ll_transition_sizeof() != C.sizeof(Transition):
        raise RuntimeError("ctypes mirror out of sync with ll_fsm.h")
    _lib = L
    return L


def default_config() -> Config:
    cfg = Config()
    lib().ll_config_default(C.byref(cfg))
    return cfg


class NativeFsm:
    def __init__(self, zone_id: str, now_ms: int, cfg: Config | None = None, **overrides) -> None:
        L = lib()
        self._buf = C.create_string_buffer(L.ll_fsm_sizeof())
        self._p = C.cast(self._buf, C.c_void_p)
        cfg = cfg or default_config()
        for k, v in overrides.items():
            setattr(cfg, k, v)
        L.ll_fsm_init(self._p, C.byref(cfg), zone_id.encode(), now_ms & 0xFFFFFFFF)

    def restore(self, state: str, now_ms: int) -> None:
        lib().ll_fsm_restore(self._p, STATES.index(state), now_ms & 0xFFFFFFFF)

    def on_vision(self, event_id: str, incident_id: str, zone_id: str, kind: int, conf: float, area: float,
                  growth: float, now_ms: int) -> str:
        v = lib().ll_fsm_on_vision(self._p, event_id.encode(), incident_id.encode(), zone_id.encode(), kind, conf,
                                   area, growth, now_ms & 0xFFFFFFFF)
        return lib().ll_verdict_name(v).decode()

    def on_wetness(self, wet: bool, now_ms: int) -> None:
        lib().ll_fsm_on_wetness(self._p, wet, now_ms & 0xFFFFFFFF)

    def on_limit(self, closed: bool, now_ms: int) -> None:
        lib().ll_fsm_on_limit(self._p, closed, now_ms & 0xFFFFFFFF)

    def on_command(self, cmd: int, now_ms: int) -> None:
        lib().ll_fsm_on_command(self._p, cmd, now_ms & 0xFFFFFFFF)

    def tick(self, now_ms: int) -> None:
        lib().ll_fsm_tick(self._p, now_ms & 0xFFFFFFFF)

    def take_actions(self) -> int:
        return lib().ll_fsm_take_actions(self._p)

    def pop_transitions(self) -> list[Transition]:
        out = []
        while True:
            t = Transition()
            if not lib().ll_fsm_pop_transition(self._p, C.byref(t)):
                return out
            out.append(t)

    @property
    def state(self) -> str:
        return STATES[lib().ll_fsm_state(self._p)]

    @property
    def reason(self) -> str:
        return lib().ll_fsm_reason(self._p).decode()

    @property
    def trigger_event_id(self) -> str:
        return lib().ll_fsm_trigger_event_id(self._p).decode()

    def counter(self, which: int) -> int:
        return lib().ll_fsm_counter(self._p, which)
