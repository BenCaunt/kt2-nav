"""Validate real Swift estimator output and prediction expiry at the receiver."""
import copy
import json
from pathlib import Path
import subprocess

import pytest

from kt2_tracking.protocol import validate_packet
from kt2_tracking.receiver import PoseStore


@pytest.fixture
def predicted_packet(tmp_path):
    binary = Path(__file__).resolve().parents[1] / "ios/.build/debug/PoseCoreChecks"
    output = tmp_path / "predicted.json"
    subprocess.run([binary, "--filter-packet", output], check=True, capture_output=True)
    return json.loads(output.read_text())


def test_actual_swift_prediction_is_separate_from_raw_observation(predicted_packet):
    packet = validate_packet(predicted_packet)
    assert packet.get("tag") is None
    estimate = packet["robot_estimate"]
    assert estimate["mode"] == "predicted"
    assert len(estimate["position_covariance_m2"]) == 9
    now = [100.]
    store = PoseStore(clock=lambda: now[0])
    store.new_connection("phone")
    store.accept(packet)
    snapshot = store.snapshot()
    assert not snapshot["pose_ready"]
    assert snapshot["usable_tag_world"] is None
    assert snapshot["estimated_tag_world"] == estimate["world_from_tag"]
    assert len(snapshot["estimate_trail"]) == 1
    now[0] += .51
    assert store.snapshot()["robot_estimate"] is None
    store.connected = False
    assert store.snapshot()["estimated_tag_world"] is None


def test_prediction_age_and_world_reset(predicted_packet):
    now = [100.]
    store = PoseStore(clock=lambda: now[0])
    store.new_connection("phone")
    packet = copy.deepcopy(predicted_packet)
    packet["robot_estimate"]["observation_age_s"] = .9
    store.accept(packet)
    assert store.snapshot()["robot_estimate"]
    now[0] += .11
    assert store.snapshot()["fresh"]
    assert store.snapshot()["robot_estimate"] is None
    packet = copy.deepcopy(packet)
    packet["sequence"] += 1
    packet["frame_timestamp_s"] += .2
    packet["camera_tracking"] = "limited"
    packet.pop("robot_estimate")
    store.accept(packet)
    assert not store.snapshot()["estimate_trail"]
    packet = copy.deepcopy(packet)
    packet["session_id"] = "new-origin"
    packet["camera_tracking"] = "normal"
    store.accept(packet)
    assert store.snapshot()["estimated_tag_world"] is None


@pytest.mark.parametrize("mutate", [
    lambda p: p["robot_estimate"].__setitem__("observation_age_s", 1.1),
    lambda p: p["robot_estimate"].__setitem__("mode", "filtered"),
    lambda p: p["robot_estimate"]["position_world_m"].__setitem__(0, 100),
    lambda p: p["robot_estimate"]["velocity_world_mps"].__setitem__(0, float("nan")),
    lambda p: p["robot_estimate"]["position_covariance_m2"].__setitem__(2, 1),
    lambda p: p["robot_estimate"]["position_covariance_m2"].__setitem__(0, -1),
    lambda p: p.__setitem__("camera_tracking", "limited"),
])
def test_malformed_estimates_rejected(predicted_packet, mutate):
    mutate(predicted_packet)
    with pytest.raises(ValueError):
        validate_packet(predicted_packet)
