"""Closed-loop demo scenarios. Each one exercises a different branch of the
evidence-to-action chain and declares the outcome the system must reach."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Leak:
    zone: str
    start_s: float
    flow_lpm: float = 0.0            # inflow while the valve is open
    initial_l: float = 0.0           # water already on the floor at start_s (a spill)
    drain_lpm: float = 0.0           # removal (mopping / drain)
    stop_s: float | None = None      # plumber fixes the joint
    controlled: bool = True          # False: the source is NOT behind this zone's valve
    source_xy: tuple | None = None   # metres; default = the zone's pipe joint


@dataclass
class Scenario:
    name: str
    title: str
    story: str
    duration_s: float
    leaks: list[Leak]
    stuck_valve_deg: dict[str, float] = field(default_factory=dict)  # zone -> max reachable angle
    camera_off_after_s: float | None = None
    commands: list[tuple[float, str, str]] = field(default_factory=list)  # (t, zone, reset|close)
    expect: dict[str, tuple[str, str]] = field(default_factory=dict)       # zone -> (state, reason)
    expect_never_closed: list[str] = field(default_factory=list)


SCENARIOS: dict[str, Scenario] = {s.name: s for s in [
    Scenario(
        "leak", "Leak under the wash-basin",
        "A pipe joint in bathroom-1 starts leaking 1.5 L/min. The camera sees a pool growing, the wetness "
        "probe confirms, the servo shuts the zone valve, the limit switch proves it closed and the camera "
        "proves the pool stopped growing. A plumber fixes the joint and the warden reopens the valve; "
        "the leftover puddle does not re-trigger.",
        110.0, [Leak("bathroom-1", 4.0, flow_lpm=1.5, stop_s=75.0)],
        commands=[(85.0, "bathroom-1", "reset")],
        expect={"bathroom-1": ("IDLE", "operator_reset"), "corridor-2": ("IDLE", "boot")},
    ),
    Scenario(
        "zone-lock", "Leak in the corridor only",
        "The corridor geyser line leaks. One camera watches both zones; only the corridor node acts. "
        "The bathroom node receives the same events and rejects them (zone lock).",
        80.0, [Leak("corridor-2", 4.0, flow_lpm=1.2)],
        expect={"corridor-2": ("LATCHED", "verified"), "bathroom-1": ("IDLE", "boot")},
        expect_never_closed=["bathroom-1"],
    ),
    Scenario(
        "mop", "Bucket spill being mopped (false-positive trap)",
        "Someone spills a bucket far from the wetness probe and mops it up. The camera sees water, "
        "but the pool shrinks and the probe stays dry, so the valve is never touched.",
        90.0, [Leak("bathroom-1", 4.0, initial_l=0.9, drain_lpm=0.9, source_xy=(1.6, 2.3))],
        expect_never_closed=["bathroom-1", "corridor-2"],
    ),
    Scenario(
        "stuck-valve", "Valve jammed half-way",
        "Scale build-up jams the ball valve at 40 degrees. The limit switch never closes, the node retries "
        "once, then raises FAULT and keeps the alarm on.",
        60.0, [Leak("bathroom-1", 4.0, flow_lpm=1.5)], stuck_valve_deg={"bathroom-1": 40.0},
        expect={"bathroom-1": ("FAULT", "valve_not_closed")},
    ),
    Scenario(
        "upstream", "Water source not behind this valve",
        "An overhead-tank overflow floods bathroom-1. The valve closes and the limit switch confirms it, but "
        "the camera sees the pool still growing, so the node reports FAULT leak_persists: the warden must "
        "look elsewhere.",
        130.0, [Leak("bathroom-1", 4.0, flow_lpm=1.5, controlled=False)],
        expect={"bathroom-1": ("FAULT", "leak_persists")},
    ),
    Scenario(
        "camera-down", "Camera offline: local fail-safe",
        "The camera loses power before a leak. With no vision at all, sustained local wetness closes the "
        "valve on its own after the fail-safe delay; the closure is mechanically verified.",
        330.0, [Leak("bathroom-1", 10.0, flow_lpm=1.0)], camera_off_after_s=2.0,
        expect={"bathroom-1": ("LATCHED", "mechanical_only")},
    ),
]}
