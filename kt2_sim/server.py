"""Loopback HTTP adapter and local MuJoCo workbench."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
import io
import json
from pathlib import PurePosixPath
import queue
import threading
import time
from urllib.parse import parse_qs, urlsplit

from PIL import Image

from .robot import SimulationStopped
from .hardware import HardwareBridge


class Controller:
    def __init__(self, runtime, *, hardware=None):
        self.runtime = runtime
        self.jobs = queue.Queue(maxsize=1)
        self.lock = threading.Lock()
        self.pending = False
        self.image = b""
        self.state = runtime.q.observe()
        self.files = {}
        self.last_render = -1
        self.hardware = hardware or HardwareBridge()
        self.hardware_image = b""

    def submit(self, code):
        compile(code, "<http>", "exec")
        with self.lock:
            if self.pending or self.runtime.busy:
                return False
            self.runtime.q.cancel.clear()
            self.pending = True
            self.jobs.put_nowait(("code", code))
        return True

    def stop(self):
        self.runtime.q.cancel.set()

    def reset(self):
        with self.lock:
            if self.pending or self.runtime.busy:
                return False
            self.pending = True
            self.jobs.put_nowait(("reset", None))
        return True

    def advance(self):
        try:
            kind, code = self.jobs.get_nowait()
        except queue.Empty:
            self.runtime.q.cancel.clear()
            self.runtime.q.sleep(0.02)
        else:
            try:
                if kind == "reset":
                    self.runtime.q.reset()
                    self.runtime.imu.yaw_offset = 0
                    self.runtime.last_error = None
                    self.runtime.log("[sim] reset\n")
                else:
                    self.runtime.execute(code, clear_cancel=False)
            except Exception as exc:
                self.runtime.log(f"{type(exc).__name__}: {exc}\n")
            finally:
                with self.lock:
                    self.pending = False
        self.state = self.runtime.q.observe()

    def update(self, robot, render=True):
        self.state = robot.observe()
        if render and time.monotonic() - self.last_render > 1 / 15:
            output = io.BytesIO()
            Image.fromarray(robot.render(960, 640)).save(output, format="JPEG", quality=85)
            self.image = output.getvalue()
            hardware_state = self.hardware.snapshot()
            orientation = hardware_state["orientation_deg_assumed"]
            if orientation is not None:
                output = io.BytesIO()
                Image.fromarray(robot.render(960, 640, orientation_deg=orientation,
                                             joint_targets_deg=hardware_state["joint_targets_deg"])).save(output, format="JPEG", quality=85)
                self.hardware_image = output.getvalue()
            else:
                self.hardware_image = b""
            self.last_render = time.monotonic()


def make_server(controller, port=8765):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, value, status=200, content_type="application/json"):
            body = json.dumps(value).encode() if content_type == "application/json" else value
            if isinstance(body, str):
                body = body.encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def authorized(self):
            authority = self.headers.get("Host", "")
            allowed = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
            if authority not in allowed:
                self.reply({"status": "NG", "msg": "Loopback Host required"}, 403)
                return False
            origin = self.headers.get("Origin")
            if origin and origin not in {f"http://{host}" for host in allowed}:
                self.reply({"status": "NG", "msg": "Cross-origin execution is disabled"}, 403)
                return False
            return True

        def params(self):
            return parse_qs(urlsplit(self.path).query)

        def do_GET(self):
            if not self.authorized():
                return
            path = urlsplit(self.path).path
            if path in ("/", "/ide/index.html"):
                return self.reply(files("kt2_sim").joinpath("web/index.html").read_bytes(), content_type="text/html; charset=utf-8")
            if path == "/ping":
                return self.reply({"status": "OK", "model": "B4KT2", "ver": "SIM-0.1", "simulation": True})
            if path == "/log":
                return self.reply(controller.runtime.drain_log(), content_type="text/plain; charset=utf-8")
            if path == "/sim/state":
                return self.reply({**controller.state, "busy": controller.pending or controller.runtime.busy,
                                   "last_error": controller.runtime.last_error})
            if path == "/sim/frame.jpg":
                return self.reply(controller.image, 200 if controller.image else 503, "image/jpeg")
            if path == "/hardware/state":
                return self.reply(controller.hardware.snapshot())
            if path == "/hardware/frame.jpg":
                available = controller.hardware.snapshot()["orientation_deg_assumed"] is not None
                body = controller.hardware_image if available else b""
                return self.reply(body, 200 if body else 503, "image/jpeg")
            if path == "/api":
                return self.api(self.params())
            if path == "/file":
                name = self.params().get("path", [""])[0]
                if name in controller.files:
                    return self.reply(controller.files[name], content_type="text/plain; charset=utf-8")
                return self.reply({"status": "NG", "msg": "Virtual file not found"}, 404)
            self.reply({"status": "NG", "msg": "Unsupported simulation route"}, 404)

        def api(self, params):
            operation = params.get("p", [""])[0]
            if operation == "/py/vm/break":
                controller.stop()
                return self.reply({"status": "OK"})
            if operation == "/sim/state":
                return self.reply({"status": "OK", **controller.state})
            if operation == "/sys/reboot":
                ok = controller.reset()
                return self.reply({"status": "OK" if ok else "NG"}, 200 if ok else 409)
            self.reply({"status": "NG", "msg": f"API operation {operation!r} is not simulated"}, 501)

        def do_POST(self):
            if not self.authorized():
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 <= size <= 65536:
                    return self.reply({"status": "NG", "msg": "Request limit: 64 KiB"}, 413)
                body = self.rfile.read(size).decode("utf-8")
                path = urlsplit(self.path).path
                if path == "/hardware/connect":
                    host = parse_qs(body).get("host", [""])[0]
                    try:
                        controller.hardware.connect(host)
                    except RuntimeError as exc:
                        return self.reply({"status": "NG", "msg": str(exc)}, 409)
                    return self.reply({"status": "OK", "msg": "Connecting to sensors"})
                if path == "/hardware/disconnect":
                    controller.hardware.disconnect()
                    return self.reply({"status": "OK"})
                if path in ("/hardware/action", "/hardware/pose", "/hardware/stop"):
                    try:
                        if path == "/hardware/stop":
                            controller.hardware.stop_robot()
                        elif path == "/hardware/pose":
                            frames = json.loads(parse_qs(body).get("frames", [""])[0])
                            controller.hardware.queue_pose(frames)
                        else:
                            action = parse_qs(body).get("action", [""])[0]
                            controller.hardware.queue_motion(action)
                    except RuntimeError as exc:
                        return self.reply({"status": "NG", "msg": str(exc)}, 409)
                    return self.reply({"status": "OK", "msg": "Robot request queued"})
                if path == "/py":
                    if self.headers.get_content_type() != "application/x-www-form-urlencoded":
                        return self.reply({"status": "NG", "msg": "Expected form-encoded code"}, 415)
                    code = parse_qs(body).get("code", [""])[0]
                    if not code.strip():
                        return self.reply({"status": "NG", "msg": "Empty program"}, 400)
                    accepted = controller.submit(code)
                    return self.reply({"status": "OK" if accepted else "NG", "simulation": True,
                                       "msg": "Queued" if accepted else "Program is running"}, 200 if accepted else 409)
                if path == "/api":
                    return self.api(parse_qs(body))
                if path == "/sim/reset":
                    ok = controller.reset()
                    return self.reply({"status": "OK" if ok else "NG"}, 200 if ok else 409)
                if path == "/file":
                    name = self.params().get("path", [""])[0]
                    if not name.startswith("/my/") or ".." in PurePosixPath(name).parts or name.endswith("/"):
                        return self.reply({"status": "NG", "msg": "Use a virtual /my/ file path"}, 400)
                    if len(controller.files) >= 100 and name not in controller.files:
                        return self.reply({"status": "NG", "msg": "Virtual file limit reached"}, 413)
                    controller.files[name] = body
                    return self.reply({"status": "OK"})
                self.reply({"status": "NG", "msg": "Unsupported simulation route"}, 404)
            except (ValueError, SyntaxError) as exc:
                self.reply({"status": "NG", "msg": str(exc)}, 400)

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    return server


def serve(runtime, *, port=8765, render=True):
    controller = Controller(runtime)
    server = make_server(controller, port)
    runtime.q.on_step = lambda robot: controller.update(robot, render)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"KT2 MuJoCo workbench: http://127.0.0.1:{server.server_port}", flush=True)
    print("Local trusted Python only. Ctrl-C stops the server.", flush=True)
    try:
        while True:
            controller.advance()
    except (KeyboardInterrupt, SimulationStopped):
        pass
    finally:
        controller.hardware.close()
        server.shutdown()
        server.server_close()
        runtime.q.close()
