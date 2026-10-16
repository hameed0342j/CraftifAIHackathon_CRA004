"""End-to-end: simulated world -> PipeGen -> contract -> the real C state machine -> valve."""

import os

import pytest

from simlab import fsm_native as F
from simlab.run import run
from simlab.scenarios import SCENARIOS


def test_native_fsm_binding():
    fsm = F.NativeFsm("bathroom-1", 0)
    assert fsm.state == "IDLE"
    assert fsm.on_vision("e" * 32, "i" * 32, "kitchen", 0, 0.9, 0.2, 0.3, 10) == "zone_mismatch"
    assert fsm.on_vision("f" * 32, "i" * 32, "bathroom-1", 0, 0.9, 0.2, 0.3, 20) == "accepted"
    assert fsm.state == "SUSPECT"
    fsm.on_wetness(True, 30)
    fsm.tick(3100)
    fsm.on_vision("g" * 32, "i" * 32, "bathroom-1", 1, 0.9, 0.25, 0.3, 3200)
    assert fsm.state == "CLOSED"
    assert fsm.take_actions() & F.ACT_VALVE_CLOSE
    assert [F.STATES[t.to] for t in fsm.pop_transitions()] == ["SUSPECT", "CONFIRMING", "CLOSED"]


FAST = ["leak", "zone-lock", "mop", "stuck-valve", "camera-down"]
ALL = sorted(SCENARIOS)


@pytest.mark.parametrize("name", ALL if os.environ.get("LEAKLATCH_ALL") else FAST)
def test_scenario(name, tmp_path):
    summary = run(name, backend="oracle", out=tmp_path / name, video=False)
    failed = [c["check"] for c in summary["checks"] if not c["ok"]]
    assert not failed, f"{name}: {failed} {summary['invalid_messages']}"
