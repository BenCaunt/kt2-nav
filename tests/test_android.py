"""Android port parity and adb transport. All motion runs against test doubles."""
import asyncio
import json
from pathlib import Path

import pytest

from kt2_tracking.protocol import validate_packet
from kt2_tracking.receiver import PoseStore
from kt2_tracking.usb import AndroidUSBBridge
from test_usb import (
    test_actual_swift_generated_robot_programs as check_programs,
    test_empty_native_gait_is_reported_as_failure as check_empty_gait,
)

FIXTURES = Path(__file__).resolve().parents[1] / "android/app/build/test-fixtures"


@pytest.fixture
def android_programs():
    path = FIXTURES / "programs.json"
    if not path.exists():
        pytest.skip("Run android/gradlew -p android testDebugUnitTest first")
    return json.loads(path.read_text())


@pytest.mark.parametrize("play_cost_ms", [5, 100])
def test_android_programs_execute_with_same_pacing_and_gaits(android_programs, monkeypatch, play_cost_ms):
    check_programs(android_programs, monkeypatch, play_cost_ms)


@pytest.mark.parametrize("action", ["walk_forward", "walk_back"])
def test_android_empty_gait_fails(android_programs, monkeypatch, action):
    check_empty_gait(android_programs, monkeypatch, action)


def test_android_estimator_matches_desktop_contract():
    path = FIXTURES / "predicted-packet.json"
    if not path.exists():
        pytest.skip("Run Android unit tests first")
    packet = validate_packet(json.loads(path.read_text()))
    clock = [100.]
    store = PoseStore(clock=lambda: clock[0])
    store.new_connection("Android over USB")
    store.accept(packet)
    assert store.snapshot()["robot_estimate"]["mode"] == "predicted"
    assert not store.snapshot()["pose_ready"]
    clock[0] += .51
    assert store.snapshot()["robot_estimate"] is None


def test_adb_forward_is_owned_recreated_and_never_overwrites_another_device():
    async def run():
        bridge = AndroidUSBBridge("ABCDEF12", PoseStore(), device="pixel-serial", adb="fake-adb")
        calls, forwards = [], []
        async def adb(*args, select=True):
            calls.append(args)
            if args == ("forward", "--list"):
                return "\n".join(forwards)
            if args == ("forward", "--no-rebind", "tcp:8767", "tcp:8767"):
                forwards.append("pixel-serial tcp:8767 tcp:8767")
                return ""
            if args == ("forward", "--remove", "tcp:8767"):
                forwards.clear()
                return ""
            raise AssertionError(args)
        bridge._adb = adb
        await bridge._prepare_connection()
        assert bridge.owns_forward
        await bridge._prepare_connection()
        assert sum("--no-rebind" in c for c in calls) == 1
        forwards.clear()  # unplugging removes adb forwarding; reconnect restores it
        await bridge._prepare_connection()
        assert sum("--no-rebind" in c for c in calls) == 2
        forwards[:] = ["different-phone tcp:8767 tcp:1111"]
        with pytest.raises(ConnectionError, match="already forwarded"):
            await bridge._prepare_connection()
        await bridge.close()
        assert forwards == ["different-phone tcp:8767 tcp:1111"]
    asyncio.run(run())


def test_adb_cleanup_removes_own_mapping():
    async def run():
        bridge = AndroidUSBBridge("ABCDEF12", PoseStore(), device="pixel", adb="fake-adb")
        bridge.owns_forward = True
        calls = []
        async def adb(*args, select=True):
            calls.append(args)
            return "pixel tcp:8767 tcp:8767" if args == ("forward", "--list") else ""
        bridge._adb = adb
        await bridge.close()
        assert calls[-1] == ("forward", "--remove", "tcp:8767")
        assert not bridge.owns_forward
    asyncio.run(run())
