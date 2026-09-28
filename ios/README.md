# KT2 Pose: iPhone vision + robot control over USB

The iPhone joins the robot's **xiaogui** Wi-Fi and controls the robot at
`192.168.4.1`. A USB cable carries camera/marker poses, robot status, and commands
between the iPhone and Mac. **The Mac stays on its normal internet network.**
Personal Hotspot is not used. Camera images stay on the phone.

The standard sticker is **ArUco DICT_4X4_50, ID 0, 25 mm black square** inside a
35 mm white sticker. Pose estimation uses the black edge, not the outer sticker.
The live overlay has thick, labeled X/right, Y/forward, and Z/out-of-paper arrows.

## Use it

1. Plug the unlocked iPhone into the Mac with a data-capable USB cable.
2. Open **KT2 Pose**, join **xiaogui** in iPhone Wi-Fi settings, then return to
   the app. Keep the app in the foreground.
3. Tap **Start camera**, allow camera access, and aim at the printed tag.
4. Tap **Robot motion > Connect** and allow local-network access. Connection
   verifies the B4KT2 identity and runs a fixed, non-motion capability probe.
5. On the Mac, double-click **Start KT2 USB.command** and enter the pairing code
   shown in the phone's **USB to Mac** panel. Open **http://127.0.0.1:8766/**.
6. Turn on **Enable motion** on the phone when ready to drive.

Phone controls:

- **Forward / Back:** choose 1–10 continuous native walking cycles; default 5.
  Each cycle creates a fresh native gait and plays its frames individually.
  The robot returns to stand after the whole batch. Status shows completed cycles;
  an empty gait or missing cycle confirmation is an error.
- **Walk pace:** Slow / Normal / Brisk set a minimum of 120 / 80 / 50 ms per
  frame. The robot's own clock enforces that interval, including any time spent
  in `q.play`. Normal is the default; five 16-frame cycles take at least 6.4 s.
- **Turn left / right:** choose 15°, 30°, 45°, or 90°. Uses the vendor's
  `actions.c_pivot(q, angle)` routine; actual heading accuracy remains uncalibrated.
- **Stand, Low, Head up, Head down:** use the standing frame or the robot's own
  posture offsets. Unsupported firmware routines remain disabled.
- **STOP ROBOT:** stays pinned at the bottom, stops the robot VM, and disarms
  movement. Enable motion again to continue.

Only one physical motion runs at a time. Commands are never queued or replayed
when USB reconnects. Losing an established USB link or backgrounding the app
requests Stop and disarms controls. Stop waits for any in-flight motion submission
before sending VM-break, so a delayed submission cannot follow an acknowledged
Stop. Completion comes from token-tagged robot logs, not the HTTP submission
response. Unconfirmed completion requests Stop after 12 seconds for turns/postures
or 12–30 seconds for walks, depending on cycle count; failed Stop is reported
separately. Native walking repeats are finite. Native angle turns rely
on firmware completion and the phone's timeout/Stop path; a lost robot Wi-Fi link
can prevent Stop delivery.

The app needs the foreground for ARKit. After switching back from another app,
start the camera again; the USB connection recovers automatically and movement
stays disarmed. Stop/reset/background clears the current pose. No firmware,
calibration, or robot files are rewritten.

## Mac launcher and API

The USB bridge uses the official `libusbmuxd` **iproxy**, with USB-only selection
and a loopback bind. It is installed on this Mac. On a fresh Mac:

```sh
brew install libusbmuxd
```

The launcher uses an isolated managed Python runtime to avoid the existing
Conda/readline issue. A command-line equivalent, from the repository root:

```sh
uv run --no-project --managed-python --python 3.12 --with 'aiohttp>=3.12,<4' \
  python -m kt2_tracking --usb --token PHONE_PAIRING_CODE --record
```

Use `--device IPHONE_UDID` if multiple iPhones are attached. `--usb-port` changes
the Mac's tunnel port (default 8767); `--port` changes the dashboard port (8766).
The phone always listens on loopback port 8767. `--record` writes JSONL observations
to `recordings/`; omit it to avoid recording. The existing Wi-Fi receiver mode is
retained for older senders, but the current iPhone app uses USB.

- `GET /api/state`: existing pose fields plus `link.transport`, `link.connected`,
  `link.robot`, and the latest command acknowledgement.
- `POST /api/command`: JSON `action`, optional integer `step_ms` (50–120, default
  80), `cycles` (1–10, default 1),
  integer `degrees` (5–90, default 30), and boolean `require_tracking` (default true).
- Actions: `connect`, `stop`, `walk_forward`, `walk_back`, `turn_left`,
  `turn_right`, `stand`, `crouch`, `look_up`, `look_down`.
- Motion requires the phone's **Enable motion** switch, detected firmware support,
  a fresh USB link, and no active motion. Automation requires a fresh unambiguous
  tag pose by default. The dashboard's manual controls explicitly disable only
  that pose requirement.
- HTTP success means **accepted**, not physically completed. Watch
  `link.robot.command_id` and `link.robot.motion` for completion or failure.

Example (this physically requests a turn when enabled and tracking is fresh):

```python
import json
from urllib.request import Request, urlopen
request = Request('http://127.0.0.1:8766/api/command',
    data=json.dumps({'action': 'turn_left', 'degrees': 30}).encode(),
    headers={'Content-Type': 'application/json'}, method='POST')
with urlopen(request, timeout=4) as response:
    print(json.load(response))
```

USB uses newline-delimited JSON. The Mac sends `hello` with version 1 and the
phone's pairing code. After `ready`, the phone emits replaceable `state` envelopes
with `packet` and `robot`. Mac heartbeats run every 350 ms; the phone closes a link
without a heartbeat for 1.5 seconds. Commands carry a unique UUID and the current
short-lived lease from `ready`/`pong`; expired or repeated commands are rejected.
The app rechecks connection ownership after dispatching to the UI thread.
The listener admits one client, bounds incoming messages, and keeps only one
pending observation. The Mac never refreshes pose age for repeated status frames.
The local HTTP API checks loopback peer, Host, Origin, and JSON content type.

## Install or rebuild the app

The project targets physical iPhones with iOS 17 or later. Xcode 26+ supports
recent iPhones. On a fresh checkout, run `python3 ios/bootstrap.py` (Python 3.11+)
to fetch verified OpenCV and XcodeGen dependencies. Open `ios/KT2Pose.xcodeproj`
and choose your development team. Alternatively, put `DEVELOPMENT_TEAM = YOUR_TEAM_ID`
in `ios/Signing.local.xcconfig`; that ignored file is loaded by `Signing.xcconfig`
and survives project regeneration. No personal signing team is published.

Connect and trust the iPhone, enable **Settings > Privacy & Security > Developer
Mode**, then select the phone in Xcode and Run. If a first launch says the developer
cannot be verified, briefly join an internet-connected network and use
**Settings > General > VPN & Device Management** to verify/trust the development
account. Open the app successfully, then return to the robot Wi-Fi.

For command-line builds, set `KT2_DEVICE_ID` to the phone's UDID from
`xcrun devicectl list devices`, then run from the repository root:

```sh
export DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer
xcodebuild -project ios/KT2Pose.xcodeproj -scheme KT2Pose \
  -destination "platform=iOS,id=$KT2_DEVICE_ID" -derivedDataPath ios/DerivedData \
  -allowProvisioningUpdates -allowProvisioningDeviceRegistration clean build
codesign --verify --deep --strict ios/DerivedData/Build/Products/Debug-iphoneos/KT2Pose.app
xcrun devicectl device install app --device "$KT2_DEVICE_ID" \
  ios/DerivedData/Build/Products/Debug-iphoneos/KT2Pose.app
xcrun devicectl device process launch --device "$KT2_DEVICE_ID" com.bencaunt.KT2Pose
```

Clean builds avoid a stale resource signature observed when changing from a
previous generic/unsigned build to a device-specific profile. The development
profile may expire; rebuild/reinstall to renew it when needed.
App Store distribution is not configured.

## Verification status

On September 28, the app was built, signed, installed, and run on the connected
iPhone 16 Pro Max / iOS 26.7. The real USB tunnel delivered hundreds of live ARKit
and marker observations while the phone identified the robot as B4KT2-V260201.
Phone-operated walk/stand cycles reported completion, and the user confirmed
operation. The enlarged triad was visually verified on the live camera. The Mac
dashboard was checked in the browser, including disabled controls after the phone
backgrounded and a Stop request.

Build 3 added longer walks, angle turns, posture controls, capability discovery,
and a pinned Stop button. The real USB stream was verified again, and the
physical robot reported support for all eight motion options.
A user-requested 30° left turn was observed running and then completing in the
live status. The expanded phone UI, persistent Stop button, and desktop controls
were visually checked. Turn-angle accuracy and travel distance remain uncalibrated;
completion means the native routine returned successfully.

The user subsequently confirmed that turns work but forward/back leave the legs
still. Build 3 had replaced the earlier frame-at-a-time walking path with
`q.play(gait, cycles)`. Build 4 restores individual frame playback and recreates
`actions.walk(q)` (or `x=-1`) for every cycle. Per-cycle robot logs include a
frame count, exposed over USB as `walk_cycles_completed` / `walk_frames_played`.
The phone requires confirmation of every requested cycle before reporting a
completed walk. Build 4 was built, signature-checked, and installed on the same
phone. The user confirmed that it moved the legs, but the gait was too fast to
travel effectively. Live logs showed 160 calls returning in roughly a second.
Thus a returned frame call alone does not establish that servos had time to move.

Build 5 enforces a minimum frame interval with MicroPython `ticks_ms`,
`ticks_diff`, and `sleep_ms`. It adds a pace selector on both phone and Mac.
Progress includes `walk_elapsed_ms` alongside frame/cycle counts. The walking
completion deadline scales with the requested cycles (12–30 s) to accommodate
the slower gait. Turn and posture deadlines remain 12 s. Timing is covered by
tests with both fast-returning and already-blocking playback. Build 5 is signed
and installed. The user confirmed that walking works with the paced build.

Build 6 adds a six-state constant-velocity Kalman filter, a camera/robot pose map,
and a rotated uncertainty ellipse. Swift checks cover noisy motion, learned
velocity, occlusions, pose outliers, reacquisition, duplicate timestamps, world
resets, and covariance orientation. The map has been rendered with synthetic
filtered/predicted trajectories for layout verification.
Build 6 was signed, installed, and launched on the connected phone. Live USB data
included filtered positions, velocities, and full covariances, and the actual
phone map and Mac dashboard were visually checked with a real tag. Measurement
noise/ellipse accuracy remains an initial model, not a calibrated error bound.

The Swift checks pass, as do 28 Python tests covering pose validation/freshness,
real Swift USB-server interoperability, pairing rejection, expiring leases,
duplicate commands, heartbeat loss, parameter bounds, command acknowledgements,
disconnect behavior, local HTTP access restrictions, and execution of generated
robot programs against a no-hardware test double. The probe is verified not to
invoke motors; generated multi-cycle and left/right calls use the expected counts
and signs. Walking tests now use one-shot gait iterators and a frame-only player,
verify all five cycles in both directions, and reject empty gaits. The previous
test double had incorrectly assumed support for bulk playback.

```sh
DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer swift run --package-path ios PoseCoreChecks
uv run --no-project --managed-python --python 3.12 --with 'aiohttp>=3.12,<4' --with pytest \
  python -m pytest tests/test_tracking.py tests/test_usb.py tests/test_filter.py -q
```

## Position filter and uncertainty

The phone estimates world XYZ position and velocity from accepted ArUco poses.
It uses actual capture-time intervals, a constant-velocity transition, continuous
white-acceleration process noise (PSD 0.0225 m²/s³), and a full 6×6 covariance.
The starting measurement noise model uses tag size/reprojection error and makes
depth uncertainty three times the lateral standard deviation. The viewing ray
rotates that covariance into the ARKit world. These parameters are initial
tuning values, not a calibrated sensor-accuracy guarantee.

The filter predicts through gaps up to 1 s, rejects isolated position outliers
with a 3-DOF innovation gate, and hides estimates whose per-axis standard
deviation exceeds 15 cm. Camera stop, world reset, and non-normal ARKit tracking
clear the estimate; long tag loss reacquires with zero initial velocity. It
estimates the sticker centre. Orientation is held from the last accepted tag;
angular velocity and a body-to-tag offset are not estimated.

The phone map shows a camera arrow, filtered/predicted robot arrow, raw tag dot,
recent trail, speed, and measurement age. Its ellipse uses the eigenvectors and
eigenvalues of the world X/Z position covariance: the radii are **2σ**, with the
numeric major/minor radii shown in cm. This contour contains about 86% of an
ideal 2D Gaussian, not 95%; the noise model itself is not empirically calibrated.
Green means an accepted tag update; amber/dashed means prediction. The camera
triad uses filtered translation and fades during prediction. UI projection is
non-mutating and stops on stale camera input; repainting cannot refresh a fix.

`state.packet.robot_estimate` is additive to schema v1 and is also recorded:
`mode`, `position_world_m`, `velocity_world_mps`, `position_std_m`,
`position_covariance_m2` (row-major 3×3), `world_from_tag`, and
`observation_age_s`. The Mac exposes fresh estimates as `robot_estimate` and
`estimated_tag_world`, plus `estimate_trail`. It expires them on stale USB data,
excess delivery delay, or prediction-horizon expiry. Existing `tag`,
`usable_tag_world`, `pose_ready`, and automated-motion observation requirements
continue to describe raw, fresh detections; predictions are explicitly separate.

## Coordinates and wire format

- The pose object retains schema version 1 inside the USB `state.packet` envelope.
  Only the paired USB client receives poses; the Mac dashboard listens on loopback.
- Requested processing rate: up to 15 Hz. Detection runs off the main thread.
  At most one image is being processed, one send is in flight, and one pending
  observation is retained. Frames are dropped rather than queued for replay.
- Units: **metres**. Every transform is 16 row-major numbers; translations are
  indices **3, 7, 11**. Matrices multiply column vectors. `A_from_B` maps points
  expressed in B to coordinates in A.
- `world_from_camera`: ARKit camera-to-world transform. World +Y follows gravity
  upward. World X/Z are session-relative, not a measured desk or geographic frame.
- `tag.cv_camera_from_tag`: OpenCV tag-to-camera pose. OpenCV camera axes are
  right, down, forward; ARKit camera axes are right, up, backward.
- `tag.world_from_tag = world_from_camera * diag(1,-1,-1,1) * cv_camera_from_tag`.
- Tag origin: centre of the **black square**. Tag +X points toward printed right,
  +Y toward printed top / robot front, and +Z out of the paper. This is the sticker
  frame; a rigid sticker-to-body offset has not been calibrated.
- `frame_timestamp_s`: ARKit capture timestamp, monotonic on the phone.
  `sent_unix_s`: phone wall time when processing completes. The receiver adds
  `received_unix_s` in recordings. Phone and Mac clocks are not synchronized;
  subtracting the wall times does **not** establish precise one-way latency.
- `session_id` changes on every AR reset/restart. Never combine world positions
  across session IDs. `sequence` increases within a session.
- `tag_status` is `detected`, `not_detected`, `duplicate`, `too_small`,
  `pose_failed`, or `error`. The `tag` field is absent when detection fails.
- A detected tag includes `reprojection_error_px`, `alternate_error_px`,
  `minimum_edge_px`, and `pose_ambiguous`. Two near-equal planar pose solutions
  with materially different rotations are flagged rather than silently trusted.

OpenCV detects the tag in the original, unrotated camera luma image and uses
ARKit's per-frame intrinsics, with no extra lens-distortion coefficients. Pose is
estimated using IPPE_SQUARE with its documented corner order. Candidates behind
the camera, edges smaller than 24 pixels, and reprojection RMS above 2.5 pixels
are rejected. Orientation ambiguity is flagged when the second candidate is
within 0.35 pixels RMS and differs by more than 10 degrees. These are initial
quality thresholds, not a measured accuracy guarantee.

ARKit can drift or relocalize. Moving the phone should leave the stationary tag's
world position approximately fixed; test this on the actual device. A 25 mm
marker needs enough pixels and a flat print. Before navigation, validate distances
with a ruler, verify heading signs, and calibrate the tag's offset to the robot.
This version does not establish a permanent desk coordinate frame or autonomous navigation.

## Read poses from Python

```python
import json
from urllib.request import urlopen
with urlopen('http://127.0.0.1:8766/api/state', timeout=1) as response:
    state = json.load(response)
pose = state['usable_tag_world']
if pose is not None:
    x, y, z = pose[3], pose[7], pose[11]
    forward_x, forward_z = pose[1], pose[9]
```

`usable_tag_world` is null on USB disconnect, after 0.5 seconds without a new
observation, during ARKit tracking loss or tag ambiguity, and when accumulating
stream delay exceeds 0.5 seconds. The retained raw packet is diagnostic only.

## Sources and pinned dependencies

- Turning and posture calls are from the recovered vendor Blockly generators:
  `evidence/analysis/resources/sys/web/blk/modules/b4-basic/actions/generators.js`
  and `sys/web/actions/index.html`. These are local research evidence, not required
  at runtime. No simulated gaits are uploaded to the real robot.
- [libusbmuxd / iproxy](https://github.com/libimobiledevice/libusbmuxd).
- [OpenCV 4.13.0 official release](https://github.com/opencv/opencv/releases/tag/4.13.0),
  Apache 2.0. Bootstrap pins the framework archive by SHA-256.
- [XcodeGen 2.46.0](https://github.com/yonaskolb/XcodeGen/releases/tag/2.46.0), MIT.
- [ARKit camera transform](https://developer.apple.com/documentation/arkit/arcamera/transform)
  and [intrinsics](https://developer.apple.com/documentation/arkit/arcamera/intrinsics).
- [OpenCV square pose estimation](https://docs.opencv.org/4.13.0/d5/d1f/calib3d_solvePnP.html).
