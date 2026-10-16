import json

import cv2
import numpy as np
import pytest

from pipegen.contract import SCHEMA_EVENT, iso_utc, validate
from pipegen.tracker import TrackerConfig, ZoneTracker
from pipegen.transport import InprocBus, topic_matches
from pipegen.zones import Zone


def test_tracker_detect_growth_clear():
    tr = ZoneTracker("z", TrackerConfig(on_frames=5, off_frames=10, window_s=10, update_period_s=2))
    kinds, t = [], 0.0
    for i in range(200):  # 20 s growing at 0.30 m2/min (0.005 m2/s)
        t = i * 0.1
        kinds += [e.kind for e in tr.update(t, 0.03 + 0.005 * t, 0.9)]
    assert kinds[0] == "detect" and kinds.count("detect") == 1 and "update" in kinds
    assert tr.growth == pytest.approx(0.30, rel=0.05)
    for i in range(200, 400):  # valve closed: area flat
        tr.update(i * 0.1, 0.03 + 0.005 * 20.0, 0.9)
    assert abs(tr.growth) < 0.01
    out = []
    for i in range(400, 420):  # mopped dry
        out += tr.update(i * 0.1, 0.0, 0.0)
    kinds = [e.kind for e in out]
    assert kinds[-1] == "clear" and kinds.count("clear") == 1 and not tr.active


def test_tracker_ignores_flicker():
    tr = ZoneTracker("z", TrackerConfig(on_frames=5))
    events = []
    for i in range(100):
        events += tr.update(i * 0.1, 0.1 if i % 3 == 0 else 0.0, 0.8)
    assert events == []


def test_zone_area_is_perspective_correct():
    # a 4 m x 3 m floor seen at a steep angle; measure a 1 m x 0.5 m rectangle drawn far away
    w, h, ppm = 640, 480, 100
    src = np.float32([[0, 0], [400, 0], [400, 300], [0, 300]])
    dst = np.float32([[150, 60], [490, 60], [700, 520], [-60, 520]])
    H = cv2.getPerspectiveTransform(src, dst)
    floor = np.zeros((300, 400), np.uint8)
    cv2.rectangle(floor, (150, 20), (249, 69), 1, -1)  # 1.0 m x 0.5 m near the far edge
    seen = cv2.warpPerspective(floor, H, (w, h), flags=cv2.INTER_NEAREST).astype(bool)
    pts_m = [[0, 0], [4, 0], [4, 3], [0, 3]]
    pts_img = cv2.perspectiveTransform(np.float32([[[x * ppm, y * ppm] for x, y in pts_m]]), H)[0] / [w, h]
    zone = Zone("z", polygon=pts_img.tolist(), floor_image_points=pts_img.tolist(), floor_metric_points=pts_m)
    assert zone.area_m2(seen) == pytest.approx(0.5, rel=0.06)
    naive = Zone("n", polygon=pts_img.tolist(), frame_area_m2=12.0 * w * h / zone.roi(w, h).sum())
    assert naive.area_m2(seen) < 0.4  # without the homography, far pools are under-counted


@pytest.mark.parametrize("pattern,topic,ok", [
    ("leaklatch/s/zone/+/event", "leaklatch/s/zone/bathroom-1/event", True),
    ("leaklatch/s/zone/+/event", "leaklatch/s/zone/bathroom-1/state", False),
    ("leaklatch/s/#", "leaklatch/s/zone/a/receipt", True),
    ("leaklatch/s/zone/a/cmd", "leaklatch/s/zone/ab/cmd", False),
])
def test_topic_matching(pattern, topic, ok):
    assert topic_matches(pattern, topic) is ok


@pytest.mark.parametrize("a,b,ok", [
    ("x/#", "x/zone/+/event", True), ("x/zone/+/event", "x/zone/a/event", True),
    ("x/zone/a/event", "x/zone/+/event", False), ("x/zone/+/event", "x/#", False),
])
def test_filter_covers(a, b, ok):
    from pipegen.transport import filter_covers
    assert filter_covers(a, b) is ok


def test_inproc_bus_replays_retained():
    bus = InprocBus()
    bus.publish("a/b/state", {"x": 1}, retain=True)
    got = []
    bus.subscribe("a/+/state", lambda t, p: got.append((t, p)))
    assert got == [("a/b/state", {"x": 1})]


def _event(**kw):
    e = {"schema": SCHEMA_EVENT, "event_id": "a" * 32, "incident_id": "b" * 32, "kind": "detect",
         "zone_id": "bathroom-1", "timestamp": iso_utc(1760000000.0), "confidence": 0.9, "pool_area": 0.12,
         "growth_rate": 0.3}
    e.update(kw)
    return e


def test_event_schema_accepts_spec_fields():
    validate(_event())
    validate(_event(kind="clear", evidence={"backend": "tensorrt-10", "persistence": 1.0}))


@pytest.mark.parametrize("bad", [{"confidence": 1.5}, {"zone_id": "Bathroom 1"}, {"kind": "maybe"},
                                 {"pool_area": -1}, {"extra": True}])
def test_event_schema_rejects(bad):
    with pytest.raises(Exception):
        validate(_event(**bad))


def test_firmware_json_matches_schema():
    """The receipt the ESP32 builds (ll_msg.c) has the same shape as the simulator's."""
    receipt = json.loads('{"schema":"leaklatch/receipt/v1","zone_id":"bathroom-1","seq":3,"from":"CONFIRMING",'
                         '"to":"CLOSED","reason":"confirmed","trigger_event_id":"ab12","last_event_id":"cd34",'
                         '"uptime_ms":42000,"evidence":{"confidence":0.91,"pool_area":0.14,"growth_rate":0.3,'
                         '"wet":true,"wetness_raw":1210,"limit_switch":false},"verification":{"mechanical":false,'
                         '"mechanical_ms":0,"hydraulic":false,"growth_after_close":0,"close_attempts":1}}')
    validate(receipt)
