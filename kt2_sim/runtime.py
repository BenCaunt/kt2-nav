"""Execute trusted local robot scripts with per-runtime firmware module aliases.

This is a compatibility environment, NOT a security sandbox. Regular Python
imports remain available. HTTP access is therefore restricted to loopback.
"""
import builtins
import math
import sys
import threading
import time
import traceback
import types

import numpy as np

from . import actions
from .robot import SimulationStopped


class IMU(types.ModuleType):
    def __init__(self, robot):
        super().__init__("imu")
        self.q = robot
        self.yaw_offset = 0
        for i, name in enumerate(("r", "p", "y")):
            setattr(self, f"get_{name}", lambda i=i: self._rpy(i))
        for i, axis in enumerate("xyz"):
            setattr(self, f"get_a{axis}", lambda i=i: self.q.observe()["accel_m_s2"][i] / 9.81)
            setattr(self, f"get_g{axis}", lambda i=i: math.degrees(self.q.observe()["gyro_rad_s"][i]))
            setattr(self, f"get_e{axis}", lambda i=i: self._rpy(i))

    def _rpy(self, i):
        angle = self.q.observe()["rpy_deg"][i]
        return (angle - self.yaw_offset + 180) % 360 - 180 if i == 2 else angle

    def reset_y(self):
        self.yaw_offset = self.q.observe()["rpy_deg"][2]

    @staticmethod
    def trans_r(value):
        return (value + 180) % 360 - 180

    def is_horizontal(self):
        return abs(self.get_r()) < 12 and abs(self.get_p()) < 12

    def is_backup(self):
        return self.q.data.body("shell").xmat[8] > 0.5

    def is_backdown(self):
        return self.q.data.body("shell").xmat[8] < -0.5

    def is_front_up(self):
        return self.get_p() < -20

    def is_back_up(self):
        return self.get_p() > 20

    def is_left_up(self):
        return self.get_r() > 20

    def is_right_up(self):
        return self.get_r() < -20

    def is_p_on(self):
        return abs(self.get_p()) < 12

    def is_static(self):
        return bool(np.linalg.norm(self.q.data.qvel[:3]) < 0.015 and np.linalg.norm(self.q.data.qvel[3:6]) < 0.15)

    def is_shaken(self):
        return bool(np.linalg.norm(self.q.data.sensor("accelerometer").data) > 25)

    def is_patted(self):
        return self.is_shaken()

    def is_flicked(self):
        return bool(np.linalg.norm(self.q.data.sensor("gyro").data) > 4)

    def __getattr__(self, name):
        conditions = {
            "wait_backup": self.is_backup, "wait_backdown": self.is_backdown,
            "wait_front_up": self.is_front_up, "wait_back_up": self.is_back_up,
            "wait_left_up": self.is_left_up, "wait_right_up": self.is_right_up,
            "wait_static": self.is_static, "wait_move": lambda: not self.is_static(),
            "wait_shake": self.is_shaken, "wait_pat": self.is_patted, "wait_flick": self.is_flicked,
            "wait_p_on": self.is_p_on, "wait_p_off": lambda: not self.is_p_on(),
            "wait_r_on": lambda: abs(self.get_r()) < 12, "wait_r_off": lambda: abs(self.get_r()) >= 12,
        }
        if name not in conditions:
            raise AttributeError(f"imu.{name} is not implemented by this simulator")
        def wait(timeout=10):
            end = self.q.data.time + timeout
            while not conditions[name]():
                if self.q.data.time >= end:
                    raise TimeoutError(f"{name} timed out in simulation")
                self.q.sleep(0.01)
        return wait


class LED:
    def __init__(self, robot):
        self.q = robot

    def on(self, color=0x26CCB2):
        self.q.set_led(color)

    def off(self):
        self.q.set_led(0)


class Buzzer:
    """Audio calls are observable events, not host audio synthesis."""
    def __init__(self, robot, logger):
        self.q, self.log = robot, logger

    def _event(self, name, *args):
        self.q.events.append({"time": float(self.q.data.time), "type": "buzzer", "name": name, "args": args})
        self.log(f"[buzzer] {name}{args}\n")

    def music(self, music): self._event("music", music)
    def freq(self, hz, keep=0): self._event("freq", hz, keep)
    def close(self): self._event("close")
    def hello(self): self._event("hello")
    def fire(self): self._event("fire")
    def mars(self, *args): self._event("mars", *args)


class Runtime:
    def __init__(self, robot, *, max_wall_seconds=30, max_sim_seconds=60):
        self.q = robot
        self.max_wall_seconds = max_wall_seconds
        self.max_sim_seconds = max_sim_seconds
        self._lock = threading.Lock()
        self._logs = ""
        self.busy = False
        self.last_error = None
        self.imu = IMU(robot)
        self.led = LED(robot)
        self.car = types.SimpleNamespace(led=self.led, buzzer=Buzzer(robot, self.log))
        clock = types.ModuleType("time")
        clock.sleep = robot.sleep
        clock.sleep_ms = lambda ms: robot.sleep(ms / 1000)
        clock.ticks_ms = lambda: round(robot.data.time * 1000)
        clock.ticks_us = lambda: round(robot.data.time * 1_000_000)
        clock.ticks_diff = lambda a, b: a - b
        clock.time = lambda: float(robot.data.time)
        clock.monotonic = clock.time
        self.modules = {"actions": actions, "imu": self.imu, "time": clock, "utime": clock}
        self.globals = {"__name__": "__main__", "q": robot, "car": self.car,
                        "led": self.led, "sleep": robot.sleep,
                        "_GAMEPAD_STATUS": {}, "__builtins__": dict(vars(builtins))}
        self.globals["__builtins__"]["__import__"] = self._import
        self.globals["__builtins__"]["print"] = self._print

    def _import(self, name, globals=None, locals=None, fromlist=(), level=0):
        if level == 0 and name in self.modules:
            return self.modules[name]
        return builtins.__import__(name, globals, locals, fromlist, level)

    def _print(self, *args, sep=" ", end="\n", file=None, flush=False):
        if file is not None:
            return builtins.print(*args, sep=sep, end=end, file=file, flush=flush)
        self.log(sep.join(str(a) for a in args) + end)

    def log(self, text):
        with self._lock:
            self._logs = (self._logs + text)[-100_000:]

    def drain_log(self):
        with self._lock:
            result, self._logs = self._logs, ""
            return result

    def execute(self, code, filename="<kt2>", *, clear_cancel=True):
        if self.busy:
            raise RuntimeError("A program is already running")
        compiled = compile(code, filename, "exec")
        self.busy = True
        self.last_error = None
        if clear_cancel:
            self.q.cancel.clear()
        started, sim_started = time.monotonic(), self.q.data.time
        self.q._wall_start, self.q._sim_start = started, sim_started
        previous_trace = sys.gettrace()

        def trace(frame, event, arg):
            if self.q.cancel.is_set():
                raise SimulationStopped("Program stopped")
            if time.monotonic() - started > self.max_wall_seconds or self.q.data.time - sim_started > self.max_sim_seconds:
                raise SimulationStopped("Program time limit reached")
            return trace

        try:
            sys.settrace(trace)
            exec(compiled, self.globals, self.globals)
        except SimulationStopped as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            self.log(f"[sim] {exc}\n")
        except BaseException as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            self.log(traceback.format_exc())
        finally:
            sys.settrace(previous_trace)
            self.busy = False
            self.q.cancel.clear()
            # CPU-only user code pauses physics; do not fast-forward the scene
            # afterwards to catch up with wall time spent in that code.
            self.q._wall_start = time.monotonic()
            self.q._sim_start = self.q.data.time
        return self.last_error is None
