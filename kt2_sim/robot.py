"""Simulation clock, joint-space motion and MuJoCo state."""
from contextlib import nullcontext
from dataclasses import dataclass
from importlib.resources import files
import math
import threading
import time

import mujoco
import numpy as np

JOINTS = ("front_left", "front_right", "rear_left", "rear_right")
STAND = (-75.0, -75.0, 75.0, 75.0)


@dataclass(frozen=True)
class Frame:
    angles: tuple[float, float, float, float]
    duration: float = 0.2
    hold: float = 0.0


class SimulationStopped(Exception):
    pass


class KT2Sim:
    """Four physical position actuators; all locomotion comes from contacts.

    The recovered joint order and signs are preserved. Symmetry transforms,
    frame defaults, servo constants and action trajectories are approximations.
    """

    def __init__(self, *, realtime=False, model_path=None):
        self.model = mujoco.MjModel.from_xml_path(str(model_path or files("kt2_sim").joinpath("models/kt2.xml")))
        self.data = mujoco.MjData(self.model)
        self.realtime = realtime
        self.cancel = threading.Event()
        self.viewer = None
        self.on_step = None
        self.renderer = None
        self._render_size = None
        self._orientation_data = None
        self.corrections = np.zeros(4)
        self.servo_k = np.ones(4)
        self.max_speed = 600.0  # Assumed degrees/second.
        self.events = []
        self.led_color = (0.15, 0.8, 0.7)
        self._last_observation = {}
        self._last_visual_time = -1.0
        self.reset()

    def reset(self):
        mujoco.mj_resetData(self.model, self.data)
        self.data.qpos[7:] = np.deg2rad(STAND)
        self.data.ctrl[:] = self.data.qpos[7:]
        self.target = np.array(STAND)
        self.cancel.clear()
        self.events.clear()
        self._last_visual_time = -1.0
        self._wall_start = time.monotonic()
        self._sim_start = self.data.time
        mujoco.mj_forward(self.model, self.data)
        self._last_observation = self.observe()

    def frame(self, d1, d2, d3, d4, duration=0.2, hold=0.0, *, ofs=None, x=1, y=1, z=1, auto=1):
        angles = np.array([d1, d2, d3, d4], dtype=float)
        if ofs is not None:
            offsets = np.asarray(ofs, dtype=float)
            if offsets.shape != (4,):
                raise ValueError("ofs must contain four angles")
            angles += offsets
        for name, sign in (("x", x), ("y", y), ("z", z)):
            if sign not in (-1, 1):
                raise ValueError(f"{name} must be 1 or -1")
        if x == -1:
            angles = -angles[[2, 3, 0, 1]]
        if y == -1:
            angles = angles[[1, 0, 3, 2]]
        if z == -1:
            angles = -angles
        if auto not in (0, 1):
            raise ValueError("auto must be 0 or 1")
        if auto:
            angles = angles * self.servo_k + self.corrections
        duration, hold = float(duration), float(hold)
        if not np.isfinite(angles).all() or not math.isfinite(duration) or not math.isfinite(hold):
            raise ValueError("Frame values must be finite")
        if duration < 0 or hold < 0:
            raise ValueError("Frame times cannot be negative")
        if np.any(np.abs(angles) > 150):
            raise ValueError("Joint target exceeds the simulated ±150 degree range")
        return Frame(tuple(float(a) for a in angles), duration, hold)

    f = frame

    def update(self, key, value):
        array = np.asarray(value, dtype=float)
        if array.shape != (4,) or not np.isfinite(array).all():
            raise ValueError("Expected four finite calibration values")
        if key == "servo_corrs":
            self.corrections = array.copy()
        elif key == "servo_k":
            self.servo_k = array.copy()
        else:
            raise NotImplementedError(f"Calibration option {key!r} is not simulated")

    def _step(self):
        if self.cancel.is_set():
            raise SimulationStopped("Program stopped")
        if self.viewer and not self.viewer.is_running():
            raise SimulationStopped("Viewer closed")
        with self.viewer.lock() if self.viewer else nullcontext():
            wanted = np.deg2rad(self.target)
            delta = np.deg2rad(self.max_speed) * self.model.opt.timestep
            self.data.ctrl[:] += np.clip(wanted - self.data.ctrl, -delta, delta)
            mujoco.mj_step(self.model, self.data)
            if not np.isfinite(self.data.qpos).all() or not np.isfinite(self.data.qvel).all():
                raise RuntimeError("Simulation became non-finite")
        if self.data.time - self._last_visual_time >= 1 / 30:
            self._last_visual_time = float(self.data.time)
            self._last_observation = self.observe()
            if self.viewer:
                self.viewer.cam.lookat[:] = self.data.qpos[:3]
                self.viewer.sync()
            if self.on_step:
                self.on_step(self)
        if self.realtime:
            delay = self._wall_start + self.data.time - self._sim_start - time.monotonic()
            if delay > 0:
                time.sleep(delay)

    def sleep(self, seconds):
        seconds = float(seconds)
        if not math.isfinite(seconds) or seconds < 0:
            raise ValueError("Sleep duration must be finite and nonnegative")
        for _ in range(math.ceil(seconds / self.model.opt.timestep - 1e-10)):
            self._step()

    def play(self, frames, repeat=1, *, dly=0.0):
        if not isinstance(repeat, int) or repeat < 0:
            raise ValueError("repeat must be a nonnegative integer")
        if not math.isfinite(dly) or dly < 0:
            raise ValueError("dly must be finite and nonnegative")
        frames = [frames] if isinstance(frames, Frame) else list(frames)
        if any(not isinstance(frame, Frame) for frame in frames):
            raise TypeError("q.play expects a Frame or iterable of Frames")
        # Validate the whole sequence before applying any controls, including manually built Frames.
        for frame in frames:
            self.frame(*frame.angles, frame.duration, frame.hold, auto=0)
        for _ in range(repeat):
            for frame in frames:
                start = self.target.copy()
                goal = np.array(frame.angles)
                steps = max(1, math.ceil(frame.duration / self.model.opt.timestep - 1e-10))
                for step in range(steps):
                    t = (step + 1) / steps
                    blend = t * t * (3 - 2 * t)
                    self.target[:] = start + blend * (goal - start)
                    self._step()
                self.sleep(frame.hold + dly)
        self._last_observation = self.observe()

    def observe(self):
        rotation = self.data.body("shell").xmat.reshape(3, 3)
        pitch = math.asin(float(np.clip(-rotation[2, 0], -1, 1)))
        roll = math.atan2(rotation[2, 1], rotation[2, 2])
        yaw = math.atan2(rotation[1, 0], rotation[0, 0])
        feet = {name: False for name in JOINTS}
        for contact in self.data.contact:
            for geom in (contact.geom1, contact.geom2):
                name = mujoco.mj_id2name(self.model, mujoco.mjtObj.mjOBJ_GEOM, geom) or ""
                if name.endswith("_foot"):
                    feet[name[:-5]] = True
        return {
            "time": float(self.data.time), "position": self.data.qpos[:3].tolist(),
            "quaternion_wxyz": self.data.qpos[3:7].tolist(),
            "angles_deg": np.rad2deg(self.data.qpos[7:]).tolist(), "target_deg": self.target.tolist(),
            "rpy_deg": np.rad2deg([roll, pitch, yaw]).tolist(),
            "accel_m_s2": self.data.sensor("accelerometer").data.tolist(),
            "gyro_rad_s": self.data.sensor("gyro").data.tolist(),
            "torque_nm": self.data.actuator_force.tolist(), "feet_contact": feet,
            "led_rgb": list(self.led_color), "simulation": True,
        }

    def set_led(self, color):
        if isinstance(color, str):
            color = int(color.lstrip("#"), 16)
        if isinstance(color, int):
            rgb = ((color >> 16 & 255) / 255, (color >> 8 & 255) / 255, (color & 255) / 255)
        else:
            rgb = tuple(float(v) for v in color)
            if len(rgb) != 3 or not all(math.isfinite(v) and 0 <= v <= 1 for v in rgb):
                raise ValueError("RGB values must be three numbers in [0,1]")
        self.led_color = rgb
        for name in ("led_left", "led_right", "led_front"):
            self.model.geom(name).rgba[:3] = rgb

    def render(self, width=960, height=640, *, orientation_deg=None, joint_targets_deg=None):
        data = self.data
        if orientation_deg is not None:
            angles = np.asarray(orientation_deg, dtype=float)
            if angles.shape != (3,) or not np.isfinite(angles).all():
                raise ValueError("Orientation must be three finite angles")
            if self._orientation_data is None:
                self._orientation_data = mujoco.MjData(self.model)
            data = self._orientation_data
            mujoco.mj_resetData(self.model, data)
            data.qpos[:3] = [0, 0, 0.09]  # Illustration height, not measured position.
            targets = np.asarray(STAND if joint_targets_deg is None else joint_targets_deg, dtype=float)
            if targets.shape != (4,) or not np.isfinite(targets).all():
                raise ValueError("Joint targets must be four finite angles")
            data.qpos[7:] = np.deg2rad(targets)  # Commanded targets, never measured feedback.
            cr, cp, cy = np.cos(np.deg2rad(angles) / 2)
            sr, sp, sy = np.sin(np.deg2rad(angles) / 2)
            data.qpos[3:7] = [cr*cp*cy+sr*sp*sy, sr*cp*cy-cr*sp*sy,
                              cr*sp*cy+sr*cp*sy, cr*cp*sy-sr*sp*cy]
            mujoco.mj_forward(self.model, data)
        if self.renderer is None or self._render_size != (width, height):
            if self.renderer:
                self.renderer.close()
            self.renderer = mujoco.Renderer(self.model, height=height, width=width)
            self._render_size = (width, height)
        camera = mujoco.MjvCamera()
        camera.lookat[:] = data.qpos[:3] + np.array([0, 0, -0.01])
        camera.distance = 0.28
        camera.azimuth = 135
        camera.elevation = -24
        self.renderer.update_scene(data, camera=camera)
        return self.renderer.render().copy()

    def close(self):
        if self.renderer:
            self.renderer.close()
            self.renderer = None
        if self.viewer:
            self.viewer.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
