"""Geometry, stale-data behavior, and real WebSocket receiver integration."""
import asyncio
import copy
import json

import pytest

pytest.importorskip("aiohttp")
from aiohttp import ClientSession, WSServerHandshakeError, WSMsgType
from aiohttp.test_utils import TestServer

from kt2_tracking.protocol import validate_packet, multiply
from kt2_tracking.receiver import PoseStore, create_app


def observation(sequence=1, timestamp=10):
    camera = [1,0,0,1, 0,1,0,2, 0,0,1,3, 0,0,0,1]
    cv = [1,0,0,.1, 0,-1,0,.2, 0,0,-1,.4, 0,0,0,1]
    conversion = [1,0,0,0, 0,-1,0,0, 0,0,-1,0, 0,0,0,1]
    return dict(schema_version=1, session_id="test-session", sequence=sequence,
        frame_timestamp_s=timestamp, sent_unix_s=100, camera_tracking="normal", camera_tracking_reason="",
        world_from_camera=camera, image_resolution=[1920,1440], intrinsics=dict(fx=1000,fy=1000,cx=960,cy=720), tag_status="detected",
        tag=dict(dictionary="DICT_4X4_50", id=0, side_length_m=.025, cv_camera_from_tag=cv,
            world_from_tag=multiply(multiply(camera, conversion),cv), corners_px=[800,600,870,600,870,670,800,670],
            reprojection_error_px=.15, alternate_error_px=1, minimum_edge_px=70, pose_ambiguous=False))


def test_axis_conversion_and_standard_size():
    p = observation()
    validate_packet(p)
    assert [p["tag"]["world_from_tag"][x] for x in (3,7,11)] == [1.1,1.8,2.6]
    p["tag"]["side_length_m"] = .035
    with pytest.raises(ValueError, match="0.025"):
        validate_packet(p)


@pytest.mark.parametrize("mutation", [
    lambda p: p["world_from_camera"].__setitem__(3,float("nan")),
    lambda p: p["tag"]["world_from_tag"].__setitem__(3,99),
    lambda p: p["tag"]["cv_camera_from_tag"].__setitem__(11,-1),
    lambda p: p["tag"]["world_from_tag"].__setitem__(0,-1),
    lambda p: p["tag"].__setitem__("minimum_edge_px",12),
    lambda p: p["tag"].__setitem__("reprojection_error_px",3),
    lambda p: p.__setitem__("tag_status","not_detected"),
    lambda p: p.__setitem__("sequence",True),
])
def test_invalid_poses_rejected(mutation):
    p = observation()
    mutation(p)
    with pytest.raises(ValueError):
        validate_packet(p)


def test_no_stale_pose_after_occlusion_disconnect_or_delay():
    now = [100.]
    store = PoseStore(clock=lambda: now[0])
    store.new_connection("phone")
    store.accept(observation())
    assert store.snapshot()["pose_ready"]
    now[0] += .51
    assert store.snapshot()["usable_tag_world"] is None
    now[0] = 100.1
    lost = observation(2,10.1)
    lost["tag_status"] = "not_detected"
    lost["tag"] = None
    store.accept(lost)
    assert store.snapshot()["usable_tag_world"] is None
    store.accept(observation(3,10.2))
    assert store.snapshot()["pose_ready"]
    store.connected = False
    assert not store.snapshot()["pose_ready"]
    store.connected = True
    now[0] = 102
    store.accept(observation(4,10.3))
    assert store.snapshot()["excess_delivery_delay_s"] > 1
    assert store.snapshot()["usable_tag_world"] is None


def test_quality_and_session_reset(tmp_path):
    store = PoseStore(record=tmp_path/"poses.jsonl")
    store.new_connection("phone")
    store.accept(observation())
    p = observation(2,10.1)
    p["tag"]["pose_ambiguous"] = True
    store.accept(p)
    assert not store.snapshot()["pose_ready"]
    p = observation(3,10.2)
    p["camera_tracking"] = "limited"
    store.accept(p)
    assert not store.snapshot()["pose_ready"]
    with pytest.raises(ValueError, match="Out-of-order"):
        store.accept(p)
    reset = observation()
    reset["session_id"] = "new-session"
    store.accept(reset)
    assert len(store.trail) == 1
    store.close()
    lines = (tmp_path/"poses.jsonl").read_text().splitlines()
    assert len(lines) == 4
    assert json.loads(lines[-1])["packet"]["session_id"] == "new-session"


def test_websocket_auth_schema_and_live_api():
    async def run():
        server = TestServer(create_app("testcode"))
        await server.start_server()
        try:
            async with ClientSession() as client:
                url = server.make_url("/ingest")
                with pytest.raises(WSServerHandshakeError) as error:
                    await client.ws_connect(url)
                assert error.value.status == 401
                headers = {"Authorization":"Bearer testcode"}
                with pytest.raises(WSServerHandshakeError) as error:
                    await client.ws_connect(url, headers={**headers,"Origin":"https://example.com"})
                assert error.value.status == 403
                async with client.ws_connect(url,headers=headers) as ws:
                    assert (await ws.receive_json())["type"] == "ready"
                    with pytest.raises(WSServerHandshakeError) as error:
                        await client.ws_connect(url,headers=headers)
                    assert error.value.status == 409
                    await ws.send_json(observation())
                    for _ in range(30):
                        async with client.get(server.make_url("/api/state")) as response:
                            state = await response.json()
                        if state["accepted_frames"]: break
                        await asyncio.sleep(.01)
                    assert state["pose_ready"]
                    assert state["packet"]["tag"]["side_length_m"] == .025
                    async with client.get(server.make_url("/api/state"),headers={"Origin":"https://example.com"}) as r:
                        assert r.status == 403
                    async with client.get(server.make_url("/api/state"),headers={"Host":"attacker.example"}) as r:
                        assert r.status == 403
                    await ws.send_json(observation()) # Duplicate frames close the sender.
                    closed = await ws.receive()
                    assert closed.type == WSMsgType.CLOSE
                    assert closed.data == 1008
                async with client.get(server.make_url("/api/state")) as response:
                    state = await response.json()
                assert not state["pose_ready"]
                assert state["usable_tag_world"] is None
        finally:
            await server.close()
    asyncio.run(run())
