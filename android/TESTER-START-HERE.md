# KT2 Pose — Pixel 7 Pro preview

This is an early Android port of our iPhone robot controller and marker tracker.
It targets **Pixel 7 Pro, Android 13 or later, arm64**. It is a signed, sideloadable
app, not a Play Store release. Real Pixel camera tracking and physical robot
operation have not yet been verified. Your feedback will help check both.

## Install on the phone

1. Download `KT2-Pose-0.1.0-preview.apk` to the Pixel and open it in Files.
2. If Android asks, allow installation from the app you used to open the APK,
   then install **KT2 Pose Preview**. USB debugging is **not** needed for this.
3. While the phone has internet, install or update
   [Google Play Services for AR](https://play.google.com/store/apps/details?id=com.google.ar.core).
   Open KT2 Pose and tap **Start camera**. Allow camera access and complete any
   AR installation prompt. The camera is optional for manual robot control.
4. In Android Wi-Fi settings, join the robot's **xiaogui** network. The usual
   password is **88888888**; use your robot's actual password if different.
   Choose **stay connected / use this network** if Android says it has no internet.
5. Return to KT2 Pose. Tap **Connect**. It should identify a **B4KT2** and enable
   the **Enable motion** switch. Connection itself does not move the robot.

No account, firmware flashing, calibration changes, or robot file writes are needed.
Keep the app in the foreground. Switching away disarms motion and requests Stop.

## First try

- Put the robot on a clear surface. The preview starts with **1 walk cycle** and
  **Slow** pace. Turn on **Enable motion**, then try **Stand** and one **Forward**
  cycle. Try **Back**, then a **15°** turn if those work.
- **STOP ROBOT** stays at the bottom of the screen. It disarms movement and asks
  the robot to stop its running Python program. A lost Wi-Fi link can prevent
  delivery; **Stop unconfirmed** means the app could not confirm that request.
- For tracking, tap **Start camera** after returning from Wi-Fi settings. Aim
  at **ArUco DICT_4X4_50, ID 0**, with a **25 mm black square**. The outer white
  sticker is 35 mm; the 25 mm black edge sets the distance scale.
- Keep the tag flat, well lit, and large enough in view. Move the phone slowly
  to initialize room tracking. The colored arrows show marker right, forward,
  and out of the paper. The map shows camera and robot positions.
- Green position is filtered; amber is a prediction through a brief tag gap.
  The ellipse is a modeled 2σ uncertainty contour, not a calibrated accuracy
  guarantee. Turn angle and walking distance also remain uncalibrated.

Manual controls work without the camera, a marker, a USB cable, or a computer.

## Optional computer map and Python API

The phone stays on robot Wi-Fi; the computer can keep its internet connection.
This works through USB debugging rather than USB tethering.

1. Install Python 3.11+ and Google's
   [Android SDK Platform-Tools](https://developer.android.com/tools/releases/platform-tools).
   Put the directory containing `adb` on your PATH.
2. Enable Pixel developer options: in **Settings → About phone**, tap **Build
   number** seven times. In **Settings → System → Developer options**, enable
   **USB debugging**. Connect a data-capable cable and approve **this computer's**
   debugging prompt. `adb devices` should show `device`, not `unauthorized`.
3. Extract the preview kit, open a terminal in its `desktop` directory, then run:

   ```sh
   python -m pip install -r requirements.txt
   python -m kt2_tracking --android --token PAIRING_CODE --record
   ```

   Replace `PAIRING_CODE` with the eight characters in the app's **USB to computer**
   panel. On macOS/Linux use `python3` if needed; on Windows `py` also works.
   On a Mac with `uv` installed you can double-click `Start KT2 Android.command`.
4. Open **http://127.0.0.1:8766/** on the computer. Keep KT2 Pose open on the phone.
   The camera needs to be running to see poses; USB status and Stop work without it.

If multiple phones are attached, add `--device SERIAL` from `adb devices`.
If a port is occupied, add `--usb-port 18767` or `--port 18766` as appropriate.
The receiver creates its own adb forward. Do not create a second manual forward
on the same port. Stop the receiver with Ctrl-C. `--record` saves pose/status
observations locally under `recordings`; omit it to avoid recording.

Desktop command endpoint: `POST /api/command`, JSON with `action` and optionally
`cycles` (1–10), `degrees` (5–90), `step_ms` (50–120), `require_tracking` (default
true). Actions are `connect`, `stop`, `walk_forward`, `walk_back`, `turn_left`,
`turn_right`, `stand`, `crouch`, `look_up`, `look_down`. Motion always requires
arming on the phone. HTTP acceptance is not motion completion; inspect
`GET /api/state` and its `link.robot.motion` field. Predictions do not authorize
automated motion. The dashboard's manual buttons allow operation without a tag.

## Feedback to send back

Tell us your Android version, whether Connect identifies B4KT2, whether one slow
cycle moves correctly, whether Stop works, and whether a stationary marker stays
roughly fixed on the map while the phone moves. Report the exact on-screen error
if anything fails. Under **Help test this preview**, tap **Save diagnostics** and
send the saved JSON along with your notes. It captures state before opening the
file picker, and includes no camera images, Wi-Fi passwords, or pairing code.

If the camera cannot start, check camera permission and update Google Play
Services for AR while connected to the internet. If the robot will not connect,
confirm Wi-Fi is still on xiaogui, choose to stay connected without internet, and
check that the robot responds at `http://192.168.4.1/ping` in the phone browser.

Camera images are processed on the phone. Optional desktop recordings contain
poses, not images. AR tracking uses Google Play Services for AR, which processes
data under [Google's Privacy Policy](https://policies.google.com/privacy).

Updates must use the same signing certificate. This preview does not have the
iPhone development profile's weekly expiry. Install a later matching-signed APK
over this one; don't uninstall unless asked, since uninstalling removes app data.
