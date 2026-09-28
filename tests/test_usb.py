"""USB protocol and generated robot programs; no physical robot is moved."""
import asyncio
import contextlib
import io
import json
from pathlib import Path
import socket
import subprocess
import sys
import types
import uuid

import pytest
from aiohttp import ClientSession
from aiohttp.test_utils import TestServer

from kt2_tracking.receiver import PoseStore, create_app
from kt2_tracking.usb import USBBridge

ROOT = Path(__file__).resolve().parents[1]
SWIFT = ROOT / "ios/.build/debug/PoseCoreChecks"


class RobotClock:
    """Deterministic MicroPython clock: playback can return before servos settle."""
    def __init__(self):
        self.now = 1000
        self.sleeps = []

    def ticks_ms(self):
        return self.now

    def ticks_diff(self, end, start):
        return end - start

    def sleep_ms(self, delay):
        assert delay > 0
        self.sleeps.append(delay)
        self.now += delay


@pytest.fixture
def robot_programs(tmp_path):
    assert SWIFT.exists(), "Build PoseCoreChecks before running USB integration tests"
    output = tmp_path / "programs.json"
    subprocess.run([SWIFT, "--robot-programs", output], check=True, capture_output=True)
    return json.loads(output.read_text())


@pytest.mark.parametrize("play_cost_ms", [5, 100])
def test_actual_swift_generated_robot_programs(robot_programs, monkeypatch, play_cost_ms):
    for action, code in robot_programs.items():
        clock = RobotClock()
        frames, directions, turns = [], [], []
        def play(frame):
            # Exercise the frame-at-a-time API that worked on the physical KT2.
            # Do not let the fake silently add support for bulk gait playback.
            assert isinstance(frame, tuple) and len(frame) == 5
            frames.append(frame)
            clock.now += play_cost_ms
        def walk(q, x=1):
            directions.append(x)
            # A gait may be a one-shot iterator; every cycle needs a fresh one.
            for step in range(16):
                yield (-60 + step * x, -60, 70, 70, .03)
        def frame(*args, ofs=None):
            return tuple(args[i]+(ofs[i] if ofs else 0) for i in range(4))+(args[4],)
        q = types.SimpleNamespace(frame=frame, play=play)
        actions = types.SimpleNamespace(walk=walk, c_pivot=lambda q, angle: turns.append(angle),
            ofs_stand_low=(-40,-40,40,40), ofs_head_up=(-85,-85,45,45), ofs_head_down=(-45,-45,85,85))
        with monkeypatch.context() as patch:
            patch.setitem(sys.modules, "actions", actions)
            patch.setitem(sys.modules, "time", clock)
            logs = io.StringIO()
            with contextlib.redirect_stdout(logs):
                namespace = {"q": q}
                exec(compile(code, "swift-generated-robot-program", "exec"), namespace)
        if action == "probe":
            assert not frames and not directions and not turns
            assert '"c_pivot"' in logs.getvalue()
            continue
        assert len(frames) == (81 if action.startswith("walk_") else 1)
        if action in {"stand", "walk_forward", "walk_back", "turn_left", "turn_right"}:
            assert frames[-1] == (-75, -75, 75, 75, .3)
        else:
            offsets = {"crouch":actions.ofs_stand_low,"look_up":actions.ofs_head_up,"look_down":actions.ofs_head_down}
            assert frames[-1] == offsets[action]+(.4,)
        assert directions == ([-1] * 5 if action == "walk_back" else [1] * 5 if action == "walk_forward" else [])
        if action.startswith("walk_"):
            direction = -1 if action == "walk_back" else 1
            assert frames[:-1] == [(-60 + step * direction, -60, 70, 70, .03) for step in range(16)] * 5
            messages = [json.loads(line.split(":", 2)[2]) for line in logs.getvalue().splitlines()]
            assert [value for value in messages if value["kind"] == "progress"] == [
                {"kind": "progress", "cycle": cycle, "frames_played": cycle * 16,
                 "elapsed_ms": cycle * 16 * max(80, play_cost_ms)} for cycle in range(1, 6)
            ]
            # Fast-returning hardware calls must be paced. Already slow calls
            # should not get another full interval added to their duration.
            assert clock.sleeps == ([80 - play_cost_ms] * 80 if play_cost_ms < 80 else [])
        assert turns == ([30] if action == "turn_left" else [-30] if action == "turn_right" else [])
        assert '"kind": "done"' in logs.getvalue()
        assert not any(name.startswith("_kt2_phone_") for name in namespace)


@pytest.mark.parametrize("action", ["walk_forward", "walk_back"])
def test_empty_native_gait_is_reported_as_failure(robot_programs, monkeypatch, action):
    frames = []
    q = types.SimpleNamespace(play=frames.append, frame=lambda *args: args)
    monkeypatch.setitem(sys.modules, "actions", types.SimpleNamespace(walk=lambda q, x=1: iter(())))
    monkeypatch.setitem(sys.modules, "time", RobotClock())
    logs = io.StringIO()
    namespace = {"q": q}
    with contextlib.redirect_stdout(logs):
        exec(compile(robot_programs[action], "swift-generated-robot-program", "exec"), namespace)
    messages = [json.loads(line.split(":", 2)[2]) for line in logs.getvalue().splitlines()]
    assert messages == [{"kind": "start"}, {"kind": "error", "error": "Robot returned an empty walking gait"}]
    assert frames == []
    assert not any(name.startswith("_kt2_phone_") for name in namespace)


async def until(predicate, timeout=4):
    deadline = asyncio.get_running_loop().time()+timeout
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("Timed out waiting for USB state")
        await asyncio.sleep(.03)


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_native_swift_usb_server_auth_leases_replay_and_watchdog():
    async def run():
        port = free_port()
        process = subprocess.Popen([SWIFT, "--usb-server-check", "native-test-code", str(port)], stdout=subprocess.DEVNULL)
        async def connect(token):
            for _ in range(50):
                try:
                    reader, writer = await asyncio.open_connection("127.0.0.1", port)
                    break
                except ConnectionRefusedError:
                    await asyncio.sleep(.05)
            writer.write(json.dumps({"type":"hello", "version":1, "token":token}).encode()+b"\n")
            await writer.drain()
            return reader, writer
        async def message(reader, kind):
            while True:
                line = await asyncio.wait_for(reader.readline(), 3)
                if not line: return None
                obj = json.loads(line)
                if obj["type"] == kind: return obj
        try:
            reader, writer = await connect("wrong-code")
            assert await asyncio.wait_for(reader.readline(), 2) == b""
            writer.close(); await writer.wait_closed()
            reader, writer = await connect("native-test-code")
            ready = await message(reader, "ready")
            async def command(action, lease, command_id=None, **parameters):
                value = {"type":"command", "id":command_id or str(uuid.uuid4()), "action":action, "lease":lease}
                value.update(parameters)
                writer.write(json.dumps(value).encode()+b"\n"); await writer.drain()
                return await message(reader, "command_result")
            assert not (await command("walk_forward", "old-lease"))["accepted"]
            key = str(uuid.uuid4())
            assert (await command("stand", ready["lease"], key))["accepted"]
            assert not (await command("stand", ready["lease"], key))["accepted"]
            assert not (await command("arbitrary_python", ready["lease"]))["accepted"]
            assert not (await command("walk_forward", ready["lease"], cycles=11))["accepted"]
            assert not (await command("walk_forward", ready["lease"], cycles=True))["accepted"]
            assert not (await command("turn_left", ready["lease"], degrees=180))["accepted"]
            assert not (await command("walk_forward", ready["lease"], step_ms=0))["accepted"]
            assert not (await command("walk_forward", ready["lease"], step_ms=True))["accepted"]
            assert not (await command("walk_forward", ready["lease"], step_ms=80.5))["accepted"]
            assert (await command("walk_forward", ready["lease"], step_ms=120))["accepted"]
            assert (await command("turn_right", ready["lease"], degrees=45))["accepted"]
            # No heartbeat: the phone server closes even while it is publishing poses.
            await asyncio.sleep(1.7)
            assert await message(reader, "never") is None
            writer.close(); await writer.wait_closed()
        finally:
            process.terminate(); process.wait(timeout=5)
    asyncio.run(run())


def test_usb_receiver_real_swift_frames_commands_and_disconnect():
    async def run():
        port = free_port()
        process = subprocess.Popen([SWIFT, "--usb-server-check", "native-test-code", str(port)], stdout=subprocess.DEVNULL)
        store = PoseStore()
        bridge = USBBridge("native-test-code", store, port=port, forwarded=True)
        server = TestServer(create_app("unused-wifi-code", store, usb=bridge))
        await server.start_server()
        try:
            await until(lambda: store.accepted > 2)
            assert store.snapshot()["pose_ready"]
            assert store.snapshot()["robot_estimate"]["mode"] == "filtered"
            assert len(store.snapshot()["robot_estimate"]["position_covariance_m2"]) == 9
            assert bridge.snapshot()["robot"]["can_move"]
            result = await bridge.command("stand")
            assert result["accepted"]
            assert "cycles=5" in (await bridge.command("walk_forward", cycles=5))["detail"]
            assert "degrees=45" in (await bridge.command("turn_left", degrees=45))["detail"]
            assert "step_ms=120" in (await bridge.command("walk_forward", step_ms=120))["detail"]
            with pytest.raises(ValueError): await bridge.command("walk_forward", cycles=True)
            with pytest.raises(ValueError): await bridge.command("turn_left", degrees=180)
            with pytest.raises(ValueError): await bridge.command("walk_forward", step_ms=0)
            with pytest.raises(ValueError): await bridge.command("walk_forward", step_ms=True)
            async with ClientSession() as client:
                endpoint = server.make_url("/api/command")
                async with client.post(endpoint, json={"action":"stop"}, headers={"Origin":"https://attacker.example"}) as r:
                    assert r.status == 403
                async with client.post(endpoint, data="action=stand") as r:
                    assert r.status == 415
                async with client.post(endpoint, json={"action":"eval"}) as r:
                    assert r.status == 400
                async with client.post(endpoint, json={"action":"walk_forward", "step_ms":0}) as r:
                    assert r.status == 400
                async with client.post(endpoint, json={"action":"walk_forward", "step_ms":50}) as r:
                    assert r.status == 200
                    assert "step_ms=50" in (await r.json())["detail"]
                async with client.post(endpoint, json={"action":"stop"}) as r:
                    assert r.status == 200
                    assert (await r.json())["accepted"]
                async with client.get(server.make_url("/ingest")) as r:
                    assert r.status == 403
            # Camera quality gates still apply before automated movement.
            store.latest["camera_tracking"] = "limited"
            with pytest.raises(RuntimeError, match="fresh"):
                await bridge.command("walk_forward")
            process.terminate(); process.wait(timeout=5)
            await until(lambda: not bridge.connected)
            assert store.snapshot()["usable_tag_world"] is None
            assert not bridge.snapshot()["robot"]["can_move"]
            with pytest.raises(ConnectionError):
                await bridge.command("stand")
        finally:
            await server.close()
            if process.poll() is None:
                process.terminate(); process.wait(timeout=5)
    asyncio.run(run())


def test_repeated_status_packets_do_not_refresh_old_pose():
    from test_tracking import observation
    async def run():
        writers = []
        async def phone(reader, writer):
            writers.append(writer)
            await reader.readline()
            writer.write(b'{"type":"ready","version":1,"lease":"test"}\n')
            packet = observation()
            for _ in range(15):
                writer.write(json.dumps({"type":"state", "robot":{}, "packet":packet}).encode()+b"\n")
                await writer.drain(); await asyncio.sleep(.07)
        server = await asyncio.start_server(phone, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        store = PoseStore(); bridge = USBBridge("test", store, port=port, forwarded=True)
        await bridge.start()
        try:
            await until(lambda: store.accepted == 1)
            await asyncio.sleep(.6)
            assert bridge.connected
            assert store.accepted == 1
            assert store.snapshot()["usable_tag_world"] is None
        finally:
            bridge.connected = False
            await bridge.close()
            for writer in writers: writer.close()
            server.close(); await server.wait_closed()
    asyncio.run(run())
