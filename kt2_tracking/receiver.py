from collections import deque
import hmac
from importlib.resources import files
import json
from pathlib import Path
import time
from urllib.parse import urlsplit

from aiohttp import web, WSMsgType

from .protocol import validate_packet


class PoseStore:
    def __init__(self, *, record=None, clock=time.monotonic):
        self.clock = clock
        self.latest = None
        self.received_at = None
        self.connected = False
        self.peer = None
        self.trail = deque(maxlen=600)
        self.estimate_trail = deque(maxlen=240)
        self.break_estimate_trail = True
        self.record = Path(record).open("a", encoding="utf-8") if record else None
        self.accepted = 0
        self.error = None
        self.stream_started_at = None
        self.stream_started_frame = None
        self.last_delivery_delay = 0.0

    def new_connection(self, peer):
        self.connected = True
        self.peer = peer
        self.latest = None
        self.received_at = None
        self.trail.clear()
        self.estimate_trail.clear()
        self.break_estimate_trail = True
        self.stream_started_at = None
        self.stream_started_frame = None
        self.error = None

    def accept(self, packet):
        packet = validate_packet(packet)
        previous = self.latest
        new_session = previous is None or previous["session_id"] != packet["session_id"]
        if not new_session and (packet["sequence"] <= previous["sequence"] or packet["frame_timestamp_s"] <= previous["frame_timestamp_s"]):
            raise ValueError("Out-of-order or repeated frame")
        now = self.clock()
        if new_session:
            self.trail.clear()
            self.estimate_trail.clear()
            self.break_estimate_trail = True
            self.stream_started_at = now
            self.stream_started_frame = packet["frame_timestamp_s"]
        # A clock offset cancels here. Detect growing transport/processing backlog
        # without pretending the phone and Mac wall clocks are synchronized.
        offset = now - packet["frame_timestamp_s"]
        baseline = self.stream_started_at - self.stream_started_frame
        if offset < baseline:
            self.stream_started_at = now
            self.stream_started_frame = packet["frame_timestamp_s"]
            baseline = offset
        self.last_delivery_delay = max(0, offset - baseline)
        self.latest = packet
        self.received_at = now
        self.accepted += 1
        self.error = None
        if self.snapshot()["pose_ready"]:
            transform = packet["tag"]["world_from_tag"]
            self.trail.append([transform[3], transform[7], transform[11]])
        if packet["camera_tracking"] != "normal":
            self.estimate_trail.clear()
            self.break_estimate_trail = True
        estimate = self.snapshot()["robot_estimate"]
        if estimate:
            self.estimate_trail.append({"position": estimate["position_world_m"], "predicted": estimate["mode"] == "predicted", "starts_segment": self.break_estimate_trail})
            self.break_estimate_trail = False
        else:
            self.break_estimate_trail = True
        if self.record:
            self.record.write(json.dumps({"received_unix_s": time.time(), "excess_delivery_delay_s": self.last_delivery_delay, "packet": packet}, allow_nan=False) + "\n")
            self.record.flush()

    def snapshot(self):
        age = None if self.received_at is None else max(0, self.clock() - self.received_at)
        fresh = self.connected and age is not None and age < .5 and self.last_delivery_delay < .5
        p = self.latest
        tag = p.get("tag") if p else None
        ready = bool(fresh and p["camera_tracking"] == "normal" and tag and not tag["pose_ambiguous"])
        estimate = p.get("robot_estimate") if fresh else None
        if estimate and estimate["observation_age_s"] + age + self.last_delivery_delay > 1:
            estimate = None
        return {"connected": self.connected, "peer": self.peer, "age_s": age,
                "fresh": fresh, "pose_ready": ready, "accepted_frames": self.accepted,
                "excess_delivery_delay_s": self.last_delivery_delay,
                "usable_tag_world": tag["world_from_tag"] if ready else None,
                "robot_estimate": estimate, "estimated_tag_world": estimate["world_from_tag"] if estimate else None,
                "estimate_trail": list(self.estimate_trail),
                "packet": p, "trail": list(self.trail), "error": self.error}

    def close(self):
        if self.record:
            self.record.close()


def create_app(token, store=None, usb=None):
    store = store or PoseStore()
    app = web.Application(client_max_size=32768)
    sender = None

    def local_only(request):
        if request.remote not in {"127.0.0.1", "::1"}:
            raise web.HTTPForbidden(text="Open this dashboard on the receiving Mac.")
        try:
            host = urlsplit("http://" + request.host).hostname
        except ValueError:
            host = None
        if host not in {"127.0.0.1", "localhost", "::1"}:
            raise web.HTTPForbidden(text="Loopback Host required")
        if request.headers.get("Origin") not in {None, f"http://{request.host}"}:
            raise web.HTTPForbidden(text="Cross-origin requests are disabled")

    async def index(request):
        local_only(request)
        return web.Response(body=files("kt2_tracking").joinpath("web/index.html").read_bytes(), content_type="text/html", headers={"Cache-Control": "no-store"})

    async def state(request):
        local_only(request)
        snapshot = store.snapshot()
        snapshot["link"] = usb.snapshot() if usb else {"transport": "wifi", "connected": store.connected}
        return web.json_response(snapshot, headers={"Cache-Control": "no-store"})

    async def command(request):
        local_only(request)
        if usb is None:
            raise web.HTTPConflict(text="Start the receiver in USB mode to control the robot")
        if request.content_type != "application/json":
            raise web.HTTPUnsupportedMediaType(text="Send application/json")
        try:
            body = await request.json()
            if not isinstance(body, dict) or not isinstance(body.get("action"), str) or not isinstance(body.get("require_tracking", True), bool):
                raise ValueError("Expected action and optional boolean require_tracking")
            result = await usb.command(body["action"], cycles=body.get("cycles", 1), degrees=body.get("degrees", 30), step_ms=body.get("step_ms", 80), require_tracking=body.get("require_tracking", True))
            return web.json_response(result)
        except (ValueError, TypeError) as exc:
            raise web.HTTPBadRequest(text=str(exc))
        except (ConnectionError, RuntimeError) as exc:
            raise web.HTTPConflict(text=str(exc))

    async def ingest(request):
        nonlocal sender
        if usb is not None:
            raise web.HTTPForbidden(text="USB mode accepts poses only from the paired phone tunnel")
        # Native app only. A browser cannot inject pose packets into a running robot experiment.
        if request.headers.get("Origin") is not None:
            raise web.HTTPForbidden(text="Native sender required")
        expected = "Bearer " + token
        if not hmac.compare_digest(request.headers.get("Authorization", "").encode(), expected.encode()):
            raise web.HTTPUnauthorized(text="Pairing code does not match")
        if sender is not None:
            raise web.HTTPConflict(text="An iPhone is already connected")
        ws = web.WebSocketResponse(heartbeat=3, max_msg_size=32768, compress=False)
        sender = ws
        try:
            await ws.prepare(request)
            store.new_connection(request.remote)
            await ws.send_json({"type": "ready", "schema_version": 1})
            async for message in ws:
                if message.type == WSMsgType.TEXT:
                    try:
                        store.accept(json.loads(message.data))
                    except (ValueError, TypeError, KeyError, OverflowError) as exc:
                        store.error = str(exc)
                        await ws.close(code=1008, message=str(exc).encode()[:120])
                        break
                    except OSError as exc:
                        store.error = f"Could not save recording: {exc}"
                        await ws.close(code=1011, message=b"Recording failed; inspect the Mac receiver")
                        break
                elif message.type in {WSMsgType.ERROR, WSMsgType.CLOSE}:
                    break
                else:
                    await ws.close(code=1003, message=b"Expected JSON text frames")
                    break
        finally:
            if sender is ws:
                sender = None
                store.connected = False
        return ws

    async def cleanup(_):
        if usb is not None:
            await usb.close()
        if sender is not None:
            await sender.close(code=1001, message=b"Receiver shutting down")
        store.close()

    app.router.add_get("/", index)
    app.router.add_get("/api/state", state)
    app.router.add_post("/api/command", command)
    app.router.add_get("/ingest", ingest)
    app.on_shutdown.append(cleanup)
    if usb is not None:
        async def startup(_):
            await usb.start()
        app.on_startup.append(startup)
    return app
