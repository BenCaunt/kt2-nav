# KT2 Nav

Phone-based tracking and controls for the KT2 robot, a desktop receiver, and a
MuJoCo simulator. Android and iPhone apps use a printed ArUco marker to estimate
robot position. The firmware investigation notes below describe the recovered
interfaces used by the software.

This repository includes source, tests, build scripts, documentation, and the
[printable tracking sticker](output/pdf/kt2-tracking-sticker.pdf). Raw flash dumps,
extracted vendor firmware, device evidence, camera/pose recordings, local SDKs,
credentials, and signing keys are kept outside Git. Personal signing settings
belong in the ignored local files described in the Android and iPhone guides.

## Android / Pixel 7 Pro preview

A native Android port of KT2 Pose is in [`android/`](android/README.md), with
phone-only robot controls, ARCore/ArUco tracking, the position filter/map, and an
optional adb USB link to the existing desktop receiver. It targets Pixel 7 Pro
on Android 13+, with a signed sideload APK and a tester kit. Start with the
[installation and first-test guide](android/TESTER-START-HERE.md). Physical Pixel
tracking and robot operation still need hardware verification; see the
[validation record](android/VERIFICATION.md).

## iPhone external tracking

The native **KT2 Pose** iPhone app in [`ios/`](ios/README.md) combines ARKit camera
tracking with detection of the standard printed ArUco sticker (ID 0, 25 mm black
square). The iPhone joins the robot's `xiaogui` Wi-Fi, controls forward/backward
gait cycles and stand, and sends camera/tag poses and robot status to the Mac over
USB. The Mac keeps its normal internet connection. The phone has 1–10-cycle walks,
left/right angle turns, posture buttons, a pinned Stop button, and large labeled
tracking arrows. A constant-velocity Kalman filter bridges brief tag gaps; the
phone and Mac maps show filtered/predicted position, camera pose, the recent
trail, and a rotated uncertainty ellipse. Double-click
`Start KT2 USB.command` and enter the phone's pairing code to open the live desk
view with JSONL recording and a local command API. Xcode is installed and the app
has been built, signed, and run on the connected iPhone. See the
[setup, USB protocol, and verification status](ios/README.md).

## MuJoCo simulator

A working simulator for the recovered Python and HTTP interfaces is in [`kt2_sim/`](kt2_sim/). It includes a browser workbench, four physical joint actuators, IMU readings, custom poses, approximate action routines, and video recording. See [SIMULATION.md](SIMULATION.md) for installation, API coverage, and fidelity limits.

```sh
.venv-sim/bin/python -m kt2_sim serve
# Open http://127.0.0.1:8765
```

The simulator does not require the flash dump or a connected robot. Its motion trajectories are original approximations; it does not emulate the proprietary firmware.

The **Real robot · controls & sensors** panel connects to the KT2 over Wi-Fi. It reads the IMU, offers walk/stand/Stop buttons, and has four joint sliders with transition times and a keyframe sequence builder. Motion programs sample the IMU between frames to keep the preview active. Walks use one cycle of the robot's own motion library; the separately labeled Sim buttons operate on MuJoCo. Live sensors and physical motion have been observed; the latest telemetry cadence and joint controls await device verification. See [hardware connection and motion controls](SIMULATION.md#sync-real-hardware-sensors) for status and limits.

## Investigation result

**This robot is programmable without first replacing its firmware.** Its installed firmware contains MicroPython, a Python web IDE, Blockly, and motion libraries. We have also obtained and verified a complete flash backup, so firmware research can proceed offline.

Python execution through the web API has been confirmed by live IMU programs on this unit. USB flash access also works; a standard serial Python REPL did not respond.

## Findings on this unit

| Item | Observed result |
| --- | --- |
| USB | Espressif `303a:1001`, `/dev/cu.usbmodem1101` |
| Processor | ESP32-S3, revision 0.2, dual core, 240 MHz |
| Memory | 16 MiB SPI flash; 8 MiB embedded PSRAM |
| Boot restrictions | Secure Boot disabled; Flash Encryption disabled |
| Product identifier | `B4KT2` |
| Product firmware | `V260201`, build `260205-185300` |
| Python | Customized MicroPython 1.19.1; banner `B3.4.0; MicroPython 9e2e983-dirty on 2026-02-05` |
| Framework | ESP-IDF `v4.4.3-347-g9ee3c8337d-dirty` |
| Backup | Two independent 16 MiB reads, identical SHA-256 |
| Integrity | ESP partition-table MD5, application checksum and application validation hash all valid |
| Extracted resources | 778 entries, including web UI, Python examples and packaged robot modules |

The hardware facts come from local `esptool` queries and saved firmware. The supporting device evidence is private and is not included in this repository.

## SDK and official tools

The [Kickstarter FAQ](https://www.kickstarter.com/projects/wairliving/kt2-kungfu-turtle-your-pocket-sized-fighter-robot/faqs) says the game and movement code is open source while the core OS is proprietary. Searches of the web and GitHub did not locate a maintained, downloadable KT2 SDK or source repository. That is a search result, not proof that none exists.

The original [Xiaogui manufacturer's site](https://guidan.com/index/) identifies this robot as **B4-KT2**. Its [B4 tools page](https://guidan.com/b4/index/index.html) links to a [Python IDE](https://guidan.com/apps/ide/index.html), Blockly, motion examples, file management, and startup-file configuration. Common links are rewritten by JavaScript to `/apps/`; copying their unmodified relative URLs produces misleading 404s. The international `kamerobotics.com` homepage returned only `OK` during this investigation.

More usefully, the robot itself includes these tools. Recovered local routes include:

| Route on the robot | Purpose |
| --- | --- |
| `/os.html?lang=en` | OS tools; includes English UI |
| `/ide/index.html?lang=en` | Python IDE |
| `/py.html` | Simple Python console |
| `/blk/index.html` | Blockly editor |
| `/actions/index.html?lang=en` | Motion examples |
| `/explorer/index.html` | File manager |
| `/boot-files/index.html` | Configure programs to run at boot |

The robot's own OS page documents `192.168.4.1` as its hotspot address. The factory hotspot credentials are `xiaogui` / `88888888`; confirm the actual advertised network name when connecting. These are robot defaults, not personal router credentials.

**Next practical step:** connect a computer or phone to the robot's hotspot, then open [the built-in Python IDE](http://192.168.4.1/ide/index.html?lang=en) or [OS tools](http://192.168.4.1/os.html?lang=en). These are HTTP links served by the robot itself. If using the robot on a router instead, substitute its assigned LAN IP.

## Programming interface recovered from the installed firmware

The bundled `sys/web/W.js` and IDE JavaScript use:

| Request | Behavior |
| --- | --- |
| `GET /ping` | Device identity / ping response |
| `POST /py`, URL-encoded field `code` | Execute Python |
| `GET /log` | Retrieve execution output |
| `GET /api?p=...&v=...` | Invoke an API operation with JSON arguments |
| `GET /file?path=...` | Read a file |
| `POST /file?path=...` | Save a file |

For example, the official motion page submits this Python:

```python
from actions import walk
q.play(walk(q), 3)
```

This is an **unexecuted vendor example** that requests three walking cycles. The supplied UI assumes `q` is available in its execution environment; we have not yet verified its runtime initialization. The non-motion probe below checks that before any movement experiments.

Custom Blockly generators also expose four-leg frames through `q.frame(...)`, motion playback, and event callbacks such as `check(state, g)` and `callback(q, t, state, g)`. This is a promising foundation for custom behaviors, sensor reactions and a desktop control library.

The extracted `sys/bot/` directory includes `actions.mpy`, `wiring.mpy`, `imu.mpy`, `agent.mpy`, and game modules. These blobs do not look like ordinary readable Python or standard unwrapped `.mpy` files; they appear encoded or encrypted by the vendor's custom loader. This is separate from ESP32 flash encryption, which is disabled. The full source code has not been recovered.

## Backup and recovery evidence

Full flash, including bootloader, partition table, app slots and device configuration:

- `backups/kt2-full-2026-09-10.bin`
- `backups/kt2-full-2026-09-10-verify.bin`
- `backups/SHA256SUMS`

Both local dumps have matching SHA-256 hashes. The dumps and their device-specific
checksums are not published.

The firmware also reveals this public vendor update location:

[B4KT2 V260201 application image](https://g.guidan.com/carupdate/B4KT2/V260201.bin)

Downloaded to `downloads/B4KT2-V260201-vendor.bin`: 4,151,680 bytes, SHA-256 `09075805264f47f29640f9c2f0f11e9a843c908d4bca0d73a63d2c3de4170d9e`. **Every byte matches the installed application starting at flash offset `0x30000`.** The vendor's TLS certificate was expired, so certificate validation was bypassed only for these public research downloads; the match against the independently captured device image verifies this particular binary's contents. It was not flashed.

This vendor file is an application update, not a complete device backup. Preserve the full dumps for recovery. A restore has not been attempted or tested.

| Partition | Offset | Size |
| --- | --- | --- |
| nvs | `0x9000` | `0x17000` |
| otadata | `0x20000` | `0x2000` |
| app1 | `0x30000` | `0x600000` |
| app2 (erased) | `0x630000` | `0x600000` |
| sys | `0xC30000` | `0x100000` |
| vfs | `0xD30000` | `0x2D0000` |

Backups and extracted resources are excluded from Git because they contain vendor code and unit-specific configuration. Keep local copies.

## Local tools

```sh
uv venv .venv
uv pip install --python .venv/bin/python -r requirements.txt

# Offline analysis and resource extraction; no device access:
.venv/bin/python scripts/analyze_flash.py backups/kt2-full-2026-09-10.bin

# After connecting to the robot's Wi-Fi:
.venv/bin/python scripts/kt2_http.py status
.venv/bin/python scripts/kt2_http.py probe-python
```

The HTTP probe prints the Python implementation and whether the motion object `q` exists. It does not request motion, write files, update firmware, or alter startup settings. It checks device identity before submitting code. Offline checks verified the identity gate, fixed payload and output confirmation; its live transport remains unverified until connected to the robot's network.

USB backup used Espressif's standard [esptool read-flash command](https://docs.espressif.com/projects/esptool/en/latest/esp32s3/esptool/basic-commands.html):

```sh
# Historical commands used for these backups. Choose new output names for future captures.
.venv/bin/esptool --chip esp32s3 --port /dev/cu.usbmodem1101 \
  --before usb-reset --after no-reset read-flash \
  0x0 0x1000000 backups/kt2-full-2026-09-10.bin

.venv/bin/esptool --chip esp32s3 --port /dev/cu.usbmodem1101 \
  --before no-reset --after hard-reset read-flash \
  0x0 0x1000000 backups/kt2-full-2026-09-10-verify.bin
```

The read command loads Espressif's temporary helper into RAM; it does not write flash. No erase, write-flash, eFuse programming, vendor update, calibration change or motor command was performed. Serial-port opening and bootloader queries caused brief resets. Newline and Ctrl-C probes produced no normal REPL response.

## Recommended direction

Use the existing MicroPython runtime and motion APIs first. This preserves the robot's existing motor control, sensor integration and calibration while allowing custom behavior. Replacing firmware is technically plausible given the accessible bootloader and disabled boot restrictions, but still requires mapping the board and its motor feedback/control arrangement. The firmware references a `servo5` driver; the actual wiring has not been inspected. Arbitrary ESP32 examples are not a drop-in replacement. Firmware replacement is a later option if the installed APIs prove too limiting.
