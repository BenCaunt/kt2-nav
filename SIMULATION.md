# KT2 MuJoCo simulator

Run KT2-style Python against a four-joint robot in MuJoCo, through either a local Python runner or the recovered HTTP request pattern. The browser workbench has a live camera, motion buttons, joint sliders, a Python editor, sensor telemetry, and Stop/Reset controls.

This is a working API compatibility prototype with approximate physics, not a calibrated digital twin or a firmware emulator. The model is free-floating: walking and turning come from motor torques and ground contact. Only an explicit scene reset restores its world position.

## Start the workbench

From this repository:

```sh
uv venv --python 3.12.10 .venv-sim
uv pip install --python .venv-sim/bin/python -e '.[dev]'
.venv-sim/bin/python -m kt2_sim serve
```

Open [the local workbench](http://127.0.0.1:8765). Choose **Run Python** for the loaded walking example, or use the motion buttons. **Apply pose** moves the joints to the four slider targets; the adjacent numbers are measured angles. **Reset scene** restores the model and simulation clock. **Stop** interrupts the current program and holds its most recent motor targets; physics continues.

The environment is already installed on this Mac. `.venv-sim` uses a standalone Python runtime, separate from the investigation tools in `.venv`. This avoids a crash in the existing Conda Python's `readline` extension when starting pytest.

The server binds only to `127.0.0.1` and rejects foreign browser origins. Submitted scripts run as **trusted local Python with this user's filesystem access**; this is not a security sandbox. Runtime globals persist between submissions. A normal program has a 30-second wall-clock and 60-second simulated-time budget; Stop and time limits interrupt Python code and simulator steps, but cannot forcibly preempt arbitrary blocking native extensions.

Simulation needs no USB connection, robot Wi-Fi, firmware dump, or external web service. The optional hardware link below connects to the real robot only after **Connect robot** is selected. Neither mode opens a serial port.

## Sync real hardware sensors

The workbench includes a **Real robot · controls & sensors** panel. Connect this computer to the robot's hotspot (factory defaults: `xiaogui`, password `88888888`), enter `192.168.4.1`, and select **Connect robot**. If the robot has joined your router instead, use its assigned private IPv4 address. The HTTP API works over Wi-Fi; the USB connection used for the earlier flash backup is not a verified Python/telemetry transport.

The bridge checks `GET /ping` for a B4KT2 identity and rejects simulator identities. It then submits a fixed, finite IMU-reading program through `POST /py` and consumes tagged JSON from `/log`. A one-second burst requests 10 samples at approximately 10 Hz. It renews only after receiving the preceding burst's completion marker. Connecting alone sends no motor commands. The reader temporarily uses the robot's Python execution slot; connect while other robot programs are idle.

Once fresh sensor data is available, **Robot: walk forward** and **Robot: walk back** run exactly one walking cycle and then stand. **Robot: stand** requests the standing posture. These are physical motions, so place the robot on a clear surface. The backend plays each frame returned by the native `actions.walk(q)` (or `x=-1` for backward), then calls `q.play(q.frame(-75, -75, 75, 75, 0.3))`. The standing angles come from the recovered `sys/web/blk/assets/stop.py`. This unit does **not** export `actions.stand`: the earlier wrapper failed on that call after walking. The simulator's approximate gaits are never uploaded to hardware.

Only one robot motion can be queued/running at a time. A request waits for the current sensor burst to complete, checks the device identity again, then submits the bounded motion program once. Motion programs emit IMU samples between frames, and the preview remains enabled while motion telemetry is fresh. No parallel Python thread is required. Sampling and log output add overhead to the gait; readings still pause inside an individual blocking firmware frame. The UI distinguishes queued, running, completed, failed, and unconfirmed results. A lost HTTP acknowledgment or completion marker never triggers an automatic motion retry. A reported completion confirms the Python routine returned; it does not measure displacement.

### Lower-level joint control

Select **Robot: stand** once after connecting to establish a commanded starting pose. The four **Real robot · joint control** sliders set front-left, front-right, rear-left, and rear-right targets in degrees. **Apply robot pose** sends those targets over the selected transition time. Moving a slider alone sends nothing. **Add keyframe** captures the four targets and duration; **Run robot sequence** plays the collected frames once, holding the final pose. The software bounds are ±90° per joint, 0.1–3 seconds per transition, up to 32 frames and 15 seconds total. These are application limits, not verified mechanical travel limits.

Custom transitions interpolate from the last commanded pose in approximately 50 ms segments using `q.frame` and `q.play`, emitting IMU and commanded angles after each segment. HTTP delivery is batched and slower than this nominal 20 Hz device cadence. The firmware's existing calibration remains enabled. This provides joint-position and transition-time control; torque/current commands and measured joint feedback have not been established. Stand and completed walks reestablish the standing reference; Stop, disconnect, reconnection, and uncertain motion failures clear it.

The local API accepts URL-encoded `frames` containing a JSON list of five-number arrays, for example:

```python
import json
from urllib.parse import urlencode
from urllib.request import urlopen

# After connecting and successfully running Robot: stand:
frames = [[-65, -65, 80, 80, 0.5], [-75, -75, 75, 75, 0.5]]
body = urlencode({"frames": json.dumps(frames)}).encode()
with urlopen("http://127.0.0.1:8765/hardware/pose", data=body) as response:
    print(response.read().decode())  # Queued; poll /hardware/state for the result.
```

**Stop robot** cancels queued work and sends the same `GET /api?p=/py/vm/break&v=null` request used by the vendor IDE. It also pauses the sensor link; select **Connect robot** to resume. The stop request cannot be overtaken by a delayed motion submission. An acknowledgment is displayed only after the robot accepts Stop. A network failure is reported as **Stop was not confirmed**; this HTTP control is not a hardware emergency stop. No additional `q.stop()` behavior is assumed from that method's name.

The panel shows raw `imu.get_r/p/y`, `get_ax/ay/az`, and `get_gx/gy/gz` values. A separate MuJoCo view illustrates the reported body orientation, assuming roll/pitch/yaw are degrees. **The actual units, axis signs, and rotation convention still need verification against the device.** Legs display the last commanded angles when known, including intermediate custom-pose targets. During native walks the leg targets are unknown, so the view uses an explicitly labeled standing illustration until the final stand. These are never encoder readings. Position and LED appearance remain illustrative. The physics simulation's state is never overwritten by telemetry or commanded hardware poses.

Each sample has the robot's `time.ticks_ms()` and the computer's receive timestamp. These clocks are not synchronized, and samples travel in HTTP/log batches; this is not a deterministic real-time motor-control channel. Samples older than two seconds are labeled stale, the orientation view is hidden, and new motion requests are disabled. A transport or protocol failure stops renewal; select **Connect robot** to retry after resolving it.

**Disconnect** stops receiving/renewing bursts. An idle reader already submitted normally finishes within approximately one second. If a motion is queued/running, Disconnect also requests Stop. Close the vendor IDE or other `/log` readers while connected because reading logs drains the same device-wide stream. The bridge filters its own random per-burst marker, but it still consumes other output from that stream.

The separately labeled **Sim:** buttons, simulator joint sliders, Python editor, and `POST /py` on localhost control **only the simulator**. Physical motions use the Robot controls and the `/hardware/action` or `/hardware/pose` routes. Simultaneous motion mirroring and arbitrary hardware Python are not enabled.

| Local route | Behavior |
| --- | --- |
| `POST /hardware/connect`, form `host=192.168.4.1` | Start identity verification and a fixed sensor reader asynchronously. Private IPv4 addresses only; HTTP redirects and proxies are disabled. |
| `POST /hardware/disconnect` | Stop the sensor link; request Stop if a motion is queued/running. |
| `POST /hardware/action`, form `action=walk_forward`, `walk_back`, or `stand` | Queue one robot motion after the current sensor burst. Requires fresh telemetry and discovered `q.play` / `q.frame` APIs. |
| `POST /hardware/pose`, form `frames` containing JSON | Queue bounded joint keyframes, each `[LF, RF, LR, RR, seconds]`. Requires fresh telemetry and a known commanded starting pose. |
| `POST /hardware/stop` | Cancel pending work and send the vendor VM-break request. |
| `GET /hardware/state` | Connection/error status, identity, raw telemetry, receive age, discovered method names, and feedback availability. |
| `GET /hardware/frame.jpg` | Separate orientation illustration when fresh roll/pitch/yaw are available; 503 otherwise. |

`orientation_deg_assumed` is explicitly an assumed interpretation of the raw angles. `joint_feedback` and `position_feedback` are null. `joint_targets_deg` contains the last reported commanded targets or null when unknown. `motion`, `can_move`, `can_pose`, and `can_stop` expose the physical-control status; `pose_limits` describes accepted inputs. The default state is disconnected, and neither connections nor queued motions resume automatically after a server restart. There is no route for forwarding arbitrary Python, calibration writes, or firmware operations to hardware.

Live sensor streaming has been observed: the bridge received 531 samples and identity `B4KT2-V260201`, plus the device's `q.play`, `q.frame`, `q.stop`, and IMU method names. An observed state is saved in `evidence/hardware-sensors-live-observed.json`. The user subsequently observed physical motion; `evidence/hardware-stand-missing-observed.json` records the earlier missing-`stand` failure. During this fix the KT2 address timed out. Frame-interleaved telemetry, low-level poses, preview state separation, Stop races, identity checks, and failed-delivery behavior pass local regression tests; the new cadence and joint controls still need verification on the connected robot.

## Run files, render, or embed

```sh
# Fast headless execution, final state on stdout
.venv-sim/bin/python -m kt2_sim run examples/walk.py

# Built-in demonstration, MP4 and final PNG/JSON
.venv-sim/bin/python -m kt2_sim run \
  --record artifacts/kt2-demo.mp4 \
  --snapshot artifacts/kt2-demo.png \
  --state artifacts/kt2-demo-state.json

# Native interactive MuJoCo viewer on macOS
.venv-sim/bin/python -m kt2_sim run examples/walk.py --view --hold 20

# HTTP API without rendering
.venv-sim/bin/python -m kt2_sim serve --no-render --port 8766

# Regression checks
.venv-sim/bin/python -m pytest -q
```

MuJoCo requires `mjpython` for its passive viewer on macOS; this CLI automatically relaunches through it and supplies the standalone Python library location. This handles the [upstream uv/virtualenv launch issue](https://github.com/google-deepmind/mujoco/issues/1923). The browser workbench and offscreen recording work with ordinary Python. See the [official Python viewer documentation](https://mujoco.readthedocs.io/en/stable/python.html#passive-viewer).

Use the library directly from regular Python:

```python
from kt2_sim import KT2Sim, actions

with KT2Sim() as q:
    q.play(actions.stand(q))
    q.play(actions.walk(q), 3)
    q.play(q.f(-55, -55, 85, 85, 0.5))
    print(q.observe())
```

For unchanged firmware-style imports such as `import actions` or `import imu`, run through the CLI, web console, or `kt2_sim.runtime.Runtime(q).execute(code)`. That runtime supplies `q`, `car`, `led`, and `sleep`. Aliases are scoped to that runtime instead of replacing the host's `time` module. Ordinary files imported by the script use normal CPython import behavior; this is not a full MicroPython module loader.

## Python compatibility

The original example works unchanged in the compatibility runtime:

```python
from actions import walk
q.play(walk(q), 3)
```

| Interface | Simulation behavior |
| --- | --- |
| `q.frame(a,b,c,d,duration=0.2,hold=0,ofs=None,x=1,y=1,z=1,auto=1)`; alias `q.f` | Build a joint-angle frame, in degrees. `ofs` and symmetry/calibration arguments are keyword-only. |
| `q.play(frame_or_frames, repeat=1, dly=0)` | Smooth target interpolation, servo speed and torque limits, physical stepping. `dly` is interpreted as extra delay after each frame. |
| `q.update('servo_corrs', [a,b,c,d])` | Add simulated degree corrections when making frames. |
| `q.update('servo_k', [a,b,c,d])` | Apply simulated per-joint multipliers before corrections. |
| `actions.stand`, `walk`, `walk_left`, `t_walk`, `c_pivot` | Original standing, forward/backward walking, and turning implementations. `c_pivot(q, angle)` executes using yaw feedback, also accepting the recovered wrapped form `q.play(c_pivot(q, angle))`. Turning also translates the body. |
| `actions.ofs_stand`, `ofs_stand_low`, `ofs_head_down`, `ofs_head_up` | Four posture offset arrays. Only the standing values are established by recovered code. |
| Named gestures | `xtrans`, `seesaw`, `spring`, `bark`, `shake_hand`, `push`, `pounce`, `bound`, `left_punch`, `right_punch`, `left_kick`, `right_kick`, `left_split`, `right_split`, `slide`, `throw`, `faint`. |
| Acrobatic names | `flip`, `back_flip`, `folded_flip`, `double_flip`, `left_flip`, `right_flip`, `left_back_flip`, `right_back_flip`, `turn_over` execute approximate joint sequences. They **do not reproduce the advertised flips or recovery maneuvers**. |
| `actions.one_key_reset(q)`, `assembly_check(q)` | Execute standing/joint-check routines. These do not teleport the model. |
| `imu.get_r/p/y`, `get_ex/ey/ez` | Roll/pitch/yaw in degrees. `get_e*` are treated as Euler aliases; actual firmware semantics remain unverified. |
| `imu.get_ax/ay/az`, `get_gx/gy/gz` | Body-frame accelerometer in g (includes gravity at rest), gyroscope in degrees/second. Actual firmware units are unverified. |
| `imu.reset_y`, `trans_r` | Reset the reported yaw reference; wrap an angle to ±180°. |
| `imu.is_*`, `wait_*` | Basic orientation/motion heuristics in `runtime.py`; thresholds are assumptions. Waits default to a 10-second simulated timeout. |
| `led.on(color)`, `led.off()`, `car.led.*` | Change the visible model's LED strips. Integer RGB, hex string, or normalized RGB tuple. |
| `car.buzzer.music/freq/close/hello/fire/mars` | Log events and append to `q.events`; no sound synthesis. |
| `sleep`, `time.sleep`, `utime.sleep_ms`, `ticks_ms/us/diff` | Advance/read simulation time, not wall time. |
| `q.observe()`, `q.reset()`, `q.render()` | Simulator extensions: state dictionary, scene reset, RGB camera image. |

Joint order is **front left, front right, rear left, rear right**. Viewed from above, +x is forward and +y is left. Front negative angles and rear positive angles lower the feet. The standing pose is `[-75, -75, 75, 75]`. Frames are limited to ±150° in this model; the real robot's limits have not been established. A zero-duration frame still advances one 2 ms step and obeys the servo speed limit.

The simulation's x reflection swaps front/rear joints and negates their angles; y swaps left/right; z negates all angles. These transforms, frame timing defaults, `hold`, interpolation, calibration semantics, and `dly` placement are assumptions based on visible call sites, not recovered implementation details.

Not implemented: the vendor's `agent`/`gamepad` event loop, playback callbacks, Bluetooth, Wi-Fi setup, firmware updates, OS services, custom `.mpy` loading, and complete filesystem/module execution semantics. Unknown Python methods raise exceptions; unknown `/api` operations return HTTP 501. `_GAMEPAD_STATUS` exists as an empty dictionary but has no input device behind it.

## HTTP compatibility

```sh
curl http://127.0.0.1:8765/ping

curl -X POST http://127.0.0.1:8765/py \
  --data-urlencode 'code=from actions import walk; q.play(walk(q), 3); print("done")'

curl http://127.0.0.1:8765/log
curl http://127.0.0.1:8765/sim/state

curl -X POST http://127.0.0.1:8765/api --data-urlencode 'p=/py/vm/break'
```

`POST /py` accepts URL-encoded `code` asynchronously. A second program while one is queued/running returns 409. Syntax errors return 400 before execution. Runtime errors are available in `/log` and `/sim/state.last_error`. Reading `/log` drains it, so a separate client and the web console share the same output stream.

| Route | Result |
| --- | --- |
| `GET /ping` | JSON identity with `model: B4KT2`, `ver: SIM-0.1`, `simulation: true`. |
| `POST /py` | Queue trusted Python; JSON response with `status: OK` or `NG`. |
| `GET /log` | Drain plain-text output and tracebacks. |
| `GET/POST /api`, `p=/py/vm/break` | Stop the queued or running program. |
| `GET/POST /api`, `p=/sys/reboot` | Reset the simulated scene while idle. |
| `GET/POST /api`, `p=/sim/state` | State JSON (simulator extension). |
| `GET/POST /file?path=/my/example.py` | In-memory virtual file storage, cleared on server restart, capped at 100 files and 64 KiB/request. It does not make these files importable or accessible through Python `open()`. |
| `POST /sim/reset` | Reset scene while idle. |
| `GET /sim/state` | Pose, joint angles/targets, torque, IMU, contacts, time, busy/error status. |
| `GET /sim/frame.jpg` | Latest 960×640 render, approximately 15 Hz in the workbench. |

This reproduces the recovered request pattern for custom clients. Full response schemas and all original web-IDE dependencies have not been verified against a live device; the bundled vendor IDE is not claimed to work unchanged against the simulator.

## Model provenance and calibration

| Parameter | Current value | Basis |
| --- | --- | --- |
| Four leg order and angle directions | LF, RF, LR, RR; front/rear signs opposed | Recovered calibration UI. |
| Standing angles | −75°, −75°, +75°, +75° | Recovered custom-agent and Blockly stop code. |
| Body shape | Angular box with silver front trim, LED strips and four stick legs | Simplified from the robot image embedded in the firmware. |
| Main body size | 68 × 50 × 24 mm, plus top cap | Visual estimate; not measured. |
| Leg length | 45 mm, with 6 mm lateral splay | Visual estimate; not measured. |
| Total mass | 160 g; 120 g body plus four 10 g legs | Assumed. |
| Actuator settings | ±0.12 N·m, 600°/s, kp 0.35, kv 0.012 | Assumed and tuned for stable contact simulation. |
| Ground contact | Sliding friction 0.85; elliptic friction cone | Assumed. |
| Physics timestep | 2 ms (500 Hz), implicit-fast integrator | Simulation setting. |
| Gaits and gestures | Original joint trajectories | Vendor `actions.mpy` implementation remains encoded. |

The evidence is local to the previous firmware investigation, under `evidence/analysis/resources/sys/`: `web/W.js`, `web/blk/modules/b4-basic/actions/generators.js`, `web/blk/modules/b4-advanced/actions/generators.js`, `web/blk/modules/b4-advanced/imu/generators.js`, `web/blk/modules/b4-basic/custom_agent/generators.js`, `web/blk/assets/stop.py`, and `web/calibration/`. These ignored research files are not required at runtime or copied into the simulator distribution.

To improve fidelity, measure the robot's body/hip/leg dimensions and mass, then edit `kt2_sim/models/kt2.xml`. Measure unloaded servo angle versus time and load response to tune `KT2Sim.max_speed` and the XML actuators. Record the real walk/pivot trajectories to replace `actions.py`, and verify IMU axes/units plus frame timing against the device. Motion and stability predictions should not be treated as validated for the physical KT2 until those comparisons are made.

## Verification

The automated suite covers stable four-foot support under gravity, forward/backward displacement with zero external body forces, approximate pivot angle, servo limits, joint order/reflections, repeat/timing, input rejection before motion, runtime isolation, Python timeout/recovery, yaw reference reset, all listed action names, HTTP execution/busy/error behavior, queued cancellation, origin checks, and virtual file bounds.

Tested here with Python 3.12.10, MuJoCo 3.13.0, NumPy 2.5.3, and pytest 9.1.1 on macOS arm64. The built-in demo ends upright after approximately 18.6 cm of displacement; this is a simulator result, not a physical robot measurement. Rendering and MP4 export were exercised in addition to the headless tests.
