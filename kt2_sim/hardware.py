"""KT2 sensor link and explicit, bounded native motion commands.

The single command worker serializes sensor bursts and allowlisted motions.
Stop can interrupt through the vendor VM-break endpoint. No arbitrary user
Python, calibration, filesystem, reset, or firmware commands are forwarded.
"""
import ipaddress
import json
import math
import re
import threading
import time
from urllib import request, parse
import uuid


GETTERS = ("get_r", "get_p", "get_y", "get_ax", "get_ay", "get_az",
           "get_gx", "get_gy", "get_gz")
MOTIONS = ("walk_forward", "walk_back", "stand")
STAND = [-75, -75, 75, 75]
POSE_LIMITS = {"angle_min": -90, "angle_max": 90, "duration_min": 0.1,
               "duration_max": 3, "max_frames": 32, "max_seconds": 15}
ACTIVE_MOTION = ("queued", "submitting", "running", "stopping")
PRIVATE_NETWORKS = tuple(ipaddress.ip_network(n) for n in
                         ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))


def validate_host(host):
    address = ipaddress.IPv4Address(host.strip())
    if not any(address in network for network in PRIVATE_NETWORKS):
        raise ValueError("Enter the robot's private IPv4 address, for example 192.168.4.1")
    return str(address)


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class Transport:
    def __init__(self, host):
        self.base = "http://" + validate_host(host)
        self.opener = request.build_opener(request.ProxyHandler({}), NoRedirect())

    def request(self, path, fields=None):
        body = parse.urlencode(fields).encode() if fields is not None else None
        req = request.Request(self.base + path, data=body)
        if body is not None:
            req.add_header("Content-Type", "application/x-www-form-urlencoded")
        with self.opener.open(req, timeout=2) as response:
            raw = response.read(262145)
            if len(raw) > 262144:
                raise ValueError("Robot response exceeded the telemetry size limit")
            return raw.decode("utf-8", errors="replace")


def verify_identity(raw):
    identity = json.loads(raw)
    if not isinstance(identity, dict):
        raise ValueError("Robot /ping did not return an identity object")
    label = " ".join(str(identity.get(k, "")) for k in ("model", "v"))
    version = str(identity.get("ver", ""))
    if identity.get("simulation") or "SIM" in (label + version).upper():
        raise ValueError("This endpoint is a simulator, not the physical KT2")
    if not re.search(r"(?<![A-Z0-9])B4KT2(?![A-Z0-9])", label.upper()):
        raise ValueError("Endpoint does not identify a B4KT2; telemetry was not submitted")
    if identity.get("status", "OK") != "OK":
        raise ValueError("Robot reports an unsuccessful ping")
    return identity


def telemetry_program(token):
    """One-second sensor burst, leaving regular opportunities for commands."""
    if not re.fullmatch(r"[0-9a-f]{32}", token):
        raise ValueError("Invalid telemetry token")
    prefix = "@KT2SYNC:" + token + ":"
    name = "_kt2_sensor_" + token
    return f'''def {name}():
    import imu
    import time
    try:
        import ujson as json
    except ImportError:
        import json
    print({prefix!r} + json.dumps({{"kind": "meta", "q_methods": dir(q) if "q" in globals() else [], "imu_methods": dir(imu)}}))
    for i in range(10):
        values = {{}}
        errors = {{}}
        for getter in {GETTERS!r}:
            try:
                values[getter] = getattr(imu, getter)()
            except Exception as exc:
                errors[getter] = str(exc)
        print({prefix!r} + json.dumps({{"kind": "sample", "values": values, "errors": errors, "device_ms": time.ticks_ms()}}))
        time.sleep(0.1)
    print({prefix!r} + json.dumps({{"kind": "end"}}))
try:
    {name}()
finally:
    del {name}
'''


def validate_frames(frames):
    """Only finite joint targets and durations may become robot Python."""
    if not isinstance(frames, list) or not 1 <= len(frames) <= POSE_LIMITS["max_frames"]:
        raise ValueError("Supply 1–32 frames, each [front_left, front_right, rear_left, rear_right, seconds]")
    clean = []
    for frame in frames:
        if not isinstance(frame, list) or len(frame) != 5 or not all(finite_number(v) for v in frame):
            raise ValueError("Each frame must contain five finite numbers")
        if not all(POSE_LIMITS["angle_min"] <= v <= POSE_LIMITS["angle_max"] for v in frame[:4]):
            raise ValueError("Robot joint targets must be within −90° to +90°")
        if not POSE_LIMITS["duration_min"] <= frame[4] <= POSE_LIMITS["duration_max"]:
            raise ValueError("Each transition must last 0.1–3 seconds")
        clean.append([float(v) for v in frame])
    if sum(f[4] for f in clean) > POSE_LIMITS["max_seconds"]:
        raise ValueError("A sequence may last at most 15 seconds")
    return clean


def motion_program(token, action, frames=None, start=None):
    if action not in (*MOTIONS, "pose", "sequence") or not re.fullmatch(r"[0-9a-f]{32}", token):
        raise ValueError("Unsupported robot motion")
    prefix = "@KT2SYNC:" + token + ":"
    name = "_kt2_motion_" + token
    if action in ("pose", "sequence"):
        frames = validate_frames(frames)
        if not isinstance(start, list) or len(start) != 4:
            raise ValueError("A known commanded starting pose is required")
        start = validate_frames([start + [0.1]])[0][:4]
        # Segment transitions on-device so telemetry is emitted while they run.
        body = f'''        previous = {start!r}
        for goal in {frames!r}:
            steps = max(1, int(goal[4] / 0.05 + 0.999999))
            for step in range(1, steps + 1):
                target = [previous[i] + (goal[i] - previous[i]) * step / steps for i in range(4)]
                q.play(q.frame(target[0], target[1], target[2], target[3], goal[4] / steps))
                sample(target)
            previous = goal[:4]'''
    else:
        gait = "actions.walk(q, x=-1)" if action == "walk_back" else "actions.walk(q)"
        body = "" if action == "stand" else f'''        import actions
        for frame in {gait}:
            q.play(frame)
            sample()
'''
        # The connected firmware has no actions.stand; this frame is from stop.py.
        body += f'''        q.play(q.frame(-75, -75, 75, 75, 0.3))
        sample({STAND!r})'''
    return f'''def {name}():
    import imu
    import time
    try:
        import ujson as json
    except ImportError:
        import json
    def sample(target=None):
        values = {{}}
        errors = {{}}
        for getter in {GETTERS!r}:
            try:
                values[getter] = getattr(imu, getter)()
            except Exception as exc:
                errors[getter] = str(exc)
        print({prefix!r} + json.dumps({{"kind": "sample", "values": values, "errors": errors, "device_ms": time.ticks_ms(), "joint_targets_deg": target}}))
    print({prefix!r} + json.dumps({{"kind": "motion_start", "action": {action!r}}}))
    try:
{body}
    except Exception as exc:
        print({prefix!r} + json.dumps({{"kind": "motion_error", "error": str(exc)}}))
    else:
        print({prefix!r} + json.dumps({{"kind": "motion_done"}}))
    print({prefix!r} + json.dumps({{"kind": "end"}}))
try:
    {name}()
finally:
    del {name}
'''


class PacketReader:
    def __init__(self, token):
        self.prefix = "@KT2SYNC:" + token + ":"
        self.buffer = ""

    def feed(self, chunk):
        self.buffer = (self.buffer + chunk)[-65536:]
        lines = self.buffer.split("\n")
        self.buffer = lines.pop()
        packets = []
        for line in lines:
            if not line.startswith(self.prefix):
                continue
            try:
                packet = json.loads(line[len(self.prefix):])
                if isinstance(packet, dict):
                    packets.append(packet)
            except ValueError:
                continue
        return packets


def finite_number(value):
    try:
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    except OverflowError:
        return False


class HardwareBridge:
    def __init__(self, *, transport_factory=Transport, poll_interval=0.12, burst_timeout=8):
        self.transport_factory = transport_factory
        self.poll_interval, self.burst_timeout = poll_interval, burst_timeout
        self.lock = threading.Lock()
        self.command_lock = threading.Lock()
        self.stop_event = threading.Event()
        self.worker = None
        self.stop_worker = None
        self.host = None
        self.phase = "disconnected"
        self.error = None
        self.identity = None
        self.telemetry = None
        self.capabilities = {}
        self.received = None
        self.samples = 0
        self.pending_action = None
        self.motion = None
        self.joint_targets = None

    def connect(self, host):
        host = validate_host(host)
        with self.lock:
            if (self.worker and self.worker.is_alive()) or (self.stop_worker and self.stop_worker.is_alive()):
                raise RuntimeError("Disconnect the current sensor link first")
            self.host, self.phase, self.error = host, "connecting", None
            self.identity, self.telemetry, self.received = None, None, None
            self.capabilities, self.samples = {}, 0
            self.pending_action, self.motion = None, None
            self.joint_targets = None
            self.stop_event.clear()
            self.worker = threading.Thread(target=self._run, args=(host,), daemon=True)
            self.worker.start()

    def disconnect(self):
        with self.lock:
            moving = self.motion and self.motion["status"] in ACTIVE_MOTION
            if not moving:
                self.stop_event.set()
                self.pending_action = None
                self.phase = "disconnected"
                self.joint_targets = None
        if moving:
            self.stop_robot()

    def close(self):
        self.disconnect()
        if self.worker:
            self.worker.join(3)
        if self.stop_worker:
            self.stop_worker.join(3)

    def queue_motion(self, action):
        if action not in MOTIONS:
            raise ValueError("Choose walk_forward, walk_back, or stand")
        self._queue(action)

    def queue_pose(self, frames):
        frames = validate_frames(frames)
        self._queue("pose" if len(frames) == 1 else "sequence", frames)

    def _queue(self, action, frames=None):
        with self.lock:
            if self.motion and self.motion["status"] in ACTIVE_MOTION:
                raise RuntimeError("A robot motion is already queued or running")
            if (self.phase != "streaming" or self.stop_event.is_set() or self.received is None
                    or time.monotonic() - self.received >= 2 or not self.worker or not self.worker.is_alive()):
                raise RuntimeError("Connect to the robot and wait for fresh sensor data before moving it")
            if not {"play", "frame"}.issubset(self.capabilities.get("q_methods", [])):
                raise RuntimeError("The robot has not reported its q.play / q.frame motion API")
            if frames is not None and self.joint_targets is None:
                raise RuntimeError("Use Robot: stand first to establish the commanded starting pose")
            self.pending_action = {"action": action, "frames": frames,
                                   "start": list(self.joint_targets) if self.joint_targets is not None else None}
            self.motion = {"action": action, "status": "queued", "error": None,
                           "requested_unix": time.time()}

    def stop_robot(self):
        with self.lock:
            if not self.host or not self.identity:
                raise RuntimeError("Connect to and identify the robot first")
            if self.stop_worker and self.stop_worker.is_alive():
                return
            # Latch before taking the command lock: a delayed POST cannot pass
            # the stop request and cause a walk after Stop was acknowledged.
            self.stop_event.set()
            self.pending_action = None
            self.joint_targets = None
            self.phase = "stopping"
            self.motion = {**(self.motion or {"action": "stop"}), "status": "stopping", "error": None}
            self.stop_worker = threading.Thread(target=self._send_stop, args=(self.host,), daemon=True)
            self.stop_worker.start()

    def _send_stop(self, host):
        try:
            with self.command_lock:
                transport = self.transport_factory(host)
                response = json.loads(transport.request("/api?p=%2Fpy%2Fvm%2Fbreak&v=null"))
                if not isinstance(response, dict) or response.get("status") != "OK":
                    raise ValueError("The robot did not acknowledge Stop")
            with self.lock:
                self.phase, self.error = "stopped", None
                self.motion = {**self.motion, "status": "stop_acknowledged", "error": None}
        except Exception as exc:
            with self.lock:
                self.phase, self.error = "error", f"Stop was not confirmed: {exc}"
                self.motion = {**self.motion, "status": "stop_unconfirmed", "error": self.error}

    def snapshot(self):
        with self.lock:
            age = time.monotonic() - self.received if self.received is not None else None
            fresh = self.phase in ("streaming", "moving") and age is not None and age < 2
            phase = "stale" if self.phase == "streaming" and not fresh else self.phase
            values = (self.telemetry or {}).get("values", {})
            rpy = [values.get(name) for name in GETTERS[:3]]
            active_motion = self.motion is not None and self.motion["status"] in ACTIVE_MOTION
            can_move = (fresh and self.phase == "streaming" and not self.stop_event.is_set() and not active_motion
                        and {"play", "frame"}.issubset(self.capabilities.get("q_methods", [])))
            return {"status": phase, "host": self.host, "identity": self.identity,
                    "telemetry": self.telemetry, "capabilities": self.capabilities,
                    "samples": self.samples, "age_seconds": age, "fresh": fresh,
                    "error": self.error, "read_only": False, "motion": dict(self.motion) if self.motion else None,
                    "can_move": can_move, "can_stop": self.identity is not None and self.phase != "stopping",
                    "supported_motions": list(MOTIONS),
                    "can_pose": can_move and self.joint_targets is not None,
                    "joint_targets_deg": list(self.joint_targets) if self.joint_targets is not None else None,
                    "pose_limits": dict(POSE_LIMITS),
                    "orientation_deg_assumed": rpy if fresh and all(finite_number(v) for v in rpy) else None,
                    "joint_feedback": None, "position_feedback": None}

    def _accept(self, packet):
        if packet.get("kind") == "meta":
            with self.lock:
                self.capabilities = {
                    key: [v[:100] for v in packet.get(key, [])[:200] if isinstance(v, str)]
                    for key in ("q_methods", "imu_methods") if isinstance(packet.get(key), list)
                }
        if packet.get("kind") != "sample":
            return False
        raw = packet.get("values")
        if not isinstance(raw, dict):
            return False
        values = {key: raw[key] for key in GETTERS if finite_number(raw.get(key))}
        if not values:
            raise ValueError("The robot returned no readable IMU values")
        errors = packet.get("errors", {})
        with self.lock:
            if self.stop_event.is_set():
                return False
            self.telemetry = {"values": values, "errors": errors if isinstance(errors, dict) else {},
                              "device_ms": packet.get("device_ms") if finite_number(packet.get("device_ms")) else None,
                              "received_unix": time.time()}
            self.received = time.monotonic()
            self.samples += 1
            if "joint_targets_deg" in packet:
                targets = packet["joint_targets_deg"]
                self.joint_targets = (list(targets) if isinstance(targets, list) and len(targets) == 4
                                      and all(finite_number(v) and -90 <= v <= 90 for v in targets) else None)
            self.phase = "moving" if self.phase == "moving" else "streaming"
        return True

    def _run(self, host):
        try:
            transport = self.transport_factory(host)
            identity = verify_identity(transport.request("/ping"))
            with self.lock:
                self.identity = identity
            while not self.stop_event.is_set():
                with self.lock:
                    action, self.pending_action = self.pending_action, None
                    if action:
                        self.phase = "moving"
                        self.motion = {**self.motion, "status": "submitting"}
                        if action["frames"] is None:
                            self.joint_targets = None
                if action:
                    self._execute_motion(transport, action)
                    if self.stop_event.wait(self.poll_interval):
                        break
                token = uuid.uuid4().hex
                reader = PacketReader(token)
                with self.command_lock:
                    if self.stop_event.is_set():
                        break
                    accepted = json.loads(transport.request("/py", {"code": telemetry_program(token)}))
                if not isinstance(accepted, dict) or accepted.get("status") != "OK":
                    raise ValueError("The robot refused the sensor program; another program may be running")
                deadline = time.monotonic() + self.burst_timeout
                complete, seen = False, False
                while not self.stop_event.wait(self.poll_interval):
                    for packet in reader.feed(transport.request("/log")):
                        seen = self._accept(packet) or seen
                        complete = complete or packet.get("kind") == "end"
                    if complete:
                        if not seen:
                            raise ValueError("Sensor program finished without confirmed telemetry")
                        break
                    if time.monotonic() > deadline:
                        raise TimeoutError("Sensor stream was not confirmed. Close other robot log readers and reconnect.")
                if self.stop_event.is_set():
                    break
                # Renew only after the preceding finite burst's end marker.
                if self.stop_event.wait(self.poll_interval):
                    break
        except Exception as exc:
            with self.lock:
                if not self.stop_event.is_set():
                    self.phase, self.error = "error", f"{type(exc).__name__}: {exc}"
                    self.pending_action = None
                    self.joint_targets = None
                    if self.motion and self.motion["status"] in ACTIVE_MOTION:
                        status = "cancelled" if self.motion["status"] == "queued" else "unconfirmed"
                        self.motion = {**self.motion, "status": status, "error": self.error}
        finally:
            with self.lock:
                if self.stop_event.is_set() and self.phase not in ("stopping", "stopped", "error"):
                    self.phase = "disconnected"

    def _execute_motion(self, transport, action):
        # Recheck identity for every physical action, not just connection time.
        verify_identity(transport.request("/ping"))
        token = uuid.uuid4().hex
        reader = PacketReader(token)
        with self.command_lock:
            if self.stop_event.is_set():
                return
            accepted = json.loads(transport.request("/py", {"code": motion_program(token, **action)}))
        if not isinstance(accepted, dict) or accepted.get("status") != "OK":
            raise ValueError("The robot did not accept the motion request")
        deadline = time.monotonic() + 35
        result = None
        while not self.stop_event.wait(self.poll_interval):
            for packet in reader.feed(transport.request("/log")):
                kind = packet.get("kind")
                self._accept(packet)
                with self.lock:
                    if self.stop_event.is_set():
                        return
                    if kind == "motion_start":
                        self.motion = {**self.motion, "status": "running"}
                    elif kind == "motion_done":
                        result = ("completed", None)
                    elif kind == "motion_error":
                        result = ("failed", str(packet.get("error", "Unknown robot error"))[:1000])
                        self.joint_targets = None
                    elif kind == "end":
                        if result is None:
                            raise ValueError("Robot motion finished without a confirmed result")
                        self.motion = {**self.motion, "status": result[0], "error": result[1],
                                       "finished_unix": time.time()}
                        self.phase = "streaming"
                        return
            if time.monotonic() > deadline:
                raise TimeoutError("Motion completion was not confirmed; it will not be retried. Use Stop robot if needed.")
