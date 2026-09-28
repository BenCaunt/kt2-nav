"""Bidirectional, authenticated phone link through a USB tunnel."""
import asyncio
import contextlib
import json
from pathlib import Path
import shutil
import time
import uuid


class USBBridge:
    def __init__(self, token, store, *, port=8767, device=None, forwarded=False):
        self.token, self.store = token, store
        self.port, self.device, self.forwarded = port, device, forwarded
        self.connected = False
        self.error = "Waiting for iPhone USB listener"
        self.robot = None
        self.robot_at = None
        self.lease = None
        self.lease_at = 0
        self.writer = None
        self.process = None
        self.task = None
        self.pending = {}
        self.write_lock = asyncio.Lock()
        self.last_result = None
        self.peer_label = "iPhone over USB"

    async def _prepare_connection(self):
        """Transport-specific reconnection hook."""

    def snapshot(self):
        fresh = self.connected and self.robot_at is not None and time.monotonic()-self.robot_at < 1
        robot = dict(self.robot or {})
        robot["can_move"] = bool(fresh and robot.get("can_move"))
        robot["can_stop"] = bool(self.connected and robot.get("can_stop"))
        return {"transport": "usb", "connected": self.connected, "fresh": fresh,
                "error": self.error, "robot": robot, "last_result": self.last_result}

    async def start(self):
        if not self.forwarded:
            executable = shutil.which("iproxy") or ("/opt/homebrew/bin/iproxy" if Path("/opt/homebrew/bin/iproxy").is_file() else None)
            if not executable:
                raise RuntimeError("Install the USB tunnel with: brew install libusbmuxd")
            args = [executable, "--local", "--source", "127.0.0.1"]
            if self.device:
                args += ["--udid", self.device]
            args += [f"{self.port}:8767"]
            self.process = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
            await asyncio.sleep(.15)
            if self.process.returncode is not None:
                raise RuntimeError(f"iproxy could not listen on port {self.port}; close the other tunnel or choose --usb-port")
        self.task = asyncio.create_task(self._run())

    async def _write(self, message):
        async with self.write_lock:
            if self.writer is None:
                raise ConnectionError("USB disconnected")
            self.writer.write(json.dumps(message, allow_nan=False, separators=(",", ":")).encode()+b"\n")
            await asyncio.wait_for(self.writer.drain(), .5)

    async def _heartbeat(self):
        while True:
            await self._write({"type": "ping"})
            await asyncio.sleep(.35)

    async def _read(self, reader):
        line = await asyncio.wait_for(reader.readline(), 2)
        if not line:
            raise ConnectionError("Phone closed USB link; check pairing code and keep KT2 Pose open")
        message = json.loads(line)
        if not isinstance(message, dict):
            raise ValueError("Invalid USB message")
        return message

    async def _run(self):
        while True:
            heartbeat = None
            try:
                await self._prepare_connection()
                if self.process and self.process.returncode is not None:
                    raise ConnectionError("USB tunnel exited; restart the receiver")
                reader, self.writer = await asyncio.wait_for(asyncio.open_connection("127.0.0.1", self.port, limit=65536), 2)
                await self._write({"type": "hello", "version": 1, "token": self.token})
                ready = await self._read(reader)
                if ready.get("type") != "ready" or ready.get("version") != 1:
                    raise ValueError("Phone USB handshake failed")
                self.lease, self.lease_at = ready.get("lease"), time.monotonic()
                self.connected, self.error = True, None
                self.store.new_connection(self.peer_label)
                heartbeat = asyncio.create_task(self._heartbeat())
                while True:
                    message = await self._read(reader)
                    kind = message.get("type")
                    if kind == "pong":
                        self.lease, self.lease_at = message.get("lease"), time.monotonic()
                    elif kind == "state":
                        robot = message.get("robot")
                        if not isinstance(robot, dict):
                            raise ValueError("Missing robot state")
                        self.robot, self.robot_at = robot, time.monotonic()
                        packet = message.get("packet")
                        if packet is None:
                            self.store.latest = None
                            self.store.received_at = None
                        else:
                            previous = self.store.latest
                            # Status updates can repeat the latest observation; never refresh its age.
                            if previous is None or (packet.get("session_id"), packet.get("sequence")) != (previous["session_id"], previous["sequence"]):
                                self.store.accept(packet)
                    elif kind == "command_result":
                        self.last_result = message
                        future = self.pending.get(message.get("id"))
                        if future and not future.done():
                            future.set_result(message)
                    else:
                        raise ValueError("Unexpected USB message type")
                    if heartbeat.done():
                        await heartbeat
            except asyncio.CancelledError:
                raise
            except (OSError, ValueError, TypeError, KeyError, asyncio.TimeoutError) as exc:
                self.error = str(exc) or "USB connection timed out"
            finally:
                self.connected = False
                self.store.connected = False
                self.robot_at = None
                if heartbeat:
                    heartbeat.cancel()
                    with contextlib.suppress(asyncio.CancelledError, Exception):
                        await heartbeat
                for future in self.pending.values():
                    if not future.done():
                        future.set_exception(ConnectionError("USB lost; command will not be replayed"))
                if self.writer:
                    self.writer.close()
                    with contextlib.suppress(Exception):
                        await self.writer.wait_closed()
                    self.writer = None
            await asyncio.sleep(1)

    async def command(self, action, *, cycles=1, degrees=30, step_ms=80, require_tracking=True):
        if action not in {"walk_forward", "walk_back", "turn_left", "turn_right", "stand", "crouch", "look_up", "look_down", "stop", "connect"}:
            raise ValueError("Unsupported robot command")
        if type(cycles) is not int or not 1 <= cycles <= 10 or type(degrees) is not int or not 5 <= degrees <= 90:
            raise ValueError("Use integer cycles 1–10 and degrees 5–90")
        if type(step_ms) is not int or not 50 <= step_ms <= 120:
            raise ValueError("Use integer step_ms 50–120")
        if not self.connected or time.monotonic()-self.lease_at > 1:
            raise ConnectionError("USB is not ready")
        if action not in {"stop", "connect"}:
            if self.pending:
                raise RuntimeError("A command is already awaiting acknowledgement")
            if not self.snapshot()["robot"]["can_move"]:
                raise RuntimeError("Connect the robot and enable motion on the phone")
            if action not in self.snapshot()["robot"].get("supported_motions", []):
                raise RuntimeError("The robot has not reported support for this motion")
            if require_tracking and not self.store.snapshot()["pose_ready"]:
                raise RuntimeError("No fresh, unambiguous tag pose")
        if len(self.pending) >= 4:
            raise RuntimeError("Too many pending requests")
        command_id = str(uuid.uuid4())
        future = asyncio.get_running_loop().create_future()
        self.pending[command_id] = future
        try:
            await self._write({"type": "command", "id": command_id, "action": action, "cycles": cycles, "degrees": degrees, "step_ms": step_ms, "lease": self.lease})
            result = await asyncio.wait_for(future, 2)
            if result.get("accepted") is not True:
                raise RuntimeError(result.get("detail", "Phone rejected command"))
            return result
        except asyncio.TimeoutError as exc:
            raise RuntimeError("Command acknowledgement timed out; it will not be retried. Use Stop if needed.") from exc
        finally:
            self.pending.pop(command_id, None)

    async def close(self):
        if self.connected:
            with contextlib.suppress(Exception):
                await self.command("stop", require_tracking=False)
        if self.task:
            self.task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.task
        if self.process and self.process.returncode is None:
            self.process.terminate()
            await self.process.wait()


class AndroidUSBBridge(USBBridge):
    """Use adb's loopback forwarding, pinned to one authorized USB device."""

    def __init__(self, token, store, *, port=8767, device=None, adb=None):
        super().__init__(token, store, port=port, device=device, forwarded=True)
        self.adb = adb or shutil.which("adb")
        self.peer_label = "Android over USB"
        self.error = "Waiting for Android USB listener"
        self.owns_forward = False

    async def _adb(self, *arguments, select=True):
        args = [self.adb]
        if select:
            args += ["-s", self.device] if self.device else ["-d"]
        process = await asyncio.create_subprocess_exec(*args, *arguments,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), 5)
        except asyncio.TimeoutError:
            process.kill()
            await process.communicate()
            raise ConnectionError("adb timed out; check USB debugging authorization") from None
        if process.returncode:
            raise ConnectionError(stderr.decode(errors="replace").strip() or "adb command failed")
        return stdout.decode(errors="replace").strip()

    async def start(self):
        if not self.adb:
            raise RuntimeError("Install Android SDK Platform-Tools and put adb on PATH; see android/README.md")
        # -d selects a physical USB device, never an unrelated emulator or Wi-Fi adb.
        self.device = await self._adb("get-serialno")
        if not self.device or self.device == "unknown":
            raise RuntimeError("Connect an Android phone and accept its USB debugging prompt")
        await self._prepare_connection()
        await super().start()

    async def _prepare_connection(self):
        lines = (await self._adb("forward", "--list", select=False)).splitlines()
        local = f"tcp:{self.port}"
        matches = [line.split() for line in lines if len(line.split()) == 3 and line.split()[1] == local]
        if matches:
            if self.owns_forward and matches == [[self.device, local, "tcp:8767"]]:
                return
            raise ConnectionError(f"adb port {self.port} is already forwarded; close the other receiver or choose --usb-port")
        await self._adb("forward", "--no-rebind", local, "tcp:8767")
        self.owns_forward = True

    async def close(self):
        await super().close()
        if self.owns_forward:
            with contextlib.suppress(Exception):
                lines = (await self._adb("forward", "--list", select=False)).splitlines()
                expected = [self.device, f"tcp:{self.port}", "tcp:8767"]
                if any(line.split() == expected for line in lines):
                    await self._adb("forward", "--remove", f"tcp:{self.port}")
            self.owns_forward = False
