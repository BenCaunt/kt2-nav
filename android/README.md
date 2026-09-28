# KT2 Pose for Android

Native Java/ARCore port for Pixel 7 Pro. Start with [tester instructions](TESTER-START-HERE.md).
The source lives alongside the iPhone app, which is unchanged. The desktop receiver
now accepts either `--usb` (iPhone/iproxy) or `--android` (Android/adb).

## Included

- B4KT2 identity and non-motion capability probe; Wi-Fi-bound HTTP to 192.168.4.1
  even when cellular is Android's default internet route. No redirects/proxies.
- Paced frame-at-a-time native walking, 1–10 cycles; left/right angle turns;
  stand, low, head up/down; pinned Stop; explicit arming; one motion at a time.
- ARCore camera-to-world tracking and live preview, OpenCV ID-0 ArUco detection,
  IPPE square pose/ambiguity checks, labeled marker axes, position/velocity
  Kalman filter, top-down map and uncertainty ellipse.
- Foreground-only, loopback TCP relay via `adb forward`, with existing schema v1,
  pairing, rotating command leases, duplicate protection, heartbeat expiry,
  bounded messages and replaceable observations. Disconnect requests Stop.
- Diagnostics export, with no images, pairing code, or Wi-Fi credentials.

Minimum Android 13 (API 33), target/compile API 35, **arm64-v8a only**. The Pixel
7 Pro is on [Google's ARCore supported list](https://developers.google.com/ar/devices).
AR is optional, so manual robot controls remain available without ARCore or camera
permission. Install/update Google Play Services for AR before joining robot Wi-Fi.
The preview is tested with 4 KB memory pages; 16 KB page-size devices are outside
the verified target because the bundled C++ runtime has 4 KB ELF alignment.

The initial Android defaults are one cycle at Slow pace, suitable for a first try.
Robot program semantics and pose/filter thresholds otherwise follow the iPhone app.
The USB desktop client works on macOS, Windows and Linux with Python/aiohttp/adb;
only macOS host testing has been performed here.

## Build

Install JDK 17, Android SDK platform 35/build-tools 35.0.0/platform-tools, and set
`ANDROID_HOME` or `android/local.properties` (`sdk.dir=/absolute/path/to/sdk`).
Open `android/` in Android Studio, or from the repository root:

```sh
android/build-preview.sh
```

The script uses Gradle 8.11.1 (wrapper checksum pinned), Android Gradle Plugin
8.9.2, ARCore 1.56.0 and OpenCV 4.11.0 from Google/Maven Central. It runs release
unit tests and lint, builds a non-debuggable signed APK, then produces:

```
artifacts/kt2-android/KT2-Pose-0.1.0-preview.apk
artifacts/kt2-android/KT2-Pose-Android-preview-kit.zip
artifacts/kt2-android/START-HERE.md
artifacts/kt2-android/SHA256SUMS.txt
```

The kit contains only the APK, instructions, license notices and optional desktop
receiver. It does not include robot firmware dumps, private evidence, recordings,
the SDK, or the signing key. It is safe to hand to the tester as a project artifact.

The first build generates a local preview certificate under `.signing/preview.jks`.
**Keep and back up the private key and `.signing/preview-password.txt`** to sign
compatible updates. Both are Git-ignored and excluded from the share kit. New
keys use a randomly generated local password. Increment versionCode
and versionName for later builds, and update the packaging filename accordingly.
No Play Store publishing is configured.

For Windows, create the equivalent keystore with `keytool` using the alias and
certificate settings in `build-preview.sh`. Save your chosen keystore/key password
in `.signing/preview-password.txt`, then run `gradlew.bat testReleaseUnitTest lintRelease assembleRelease`
inside `android`, followed by `python package-preview.py`.

## Validate without a Pixel

```sh
android/gradlew -p android testDebugUnitTest connectedDebugAndroidTest lintDebug
uv run --no-project --managed-python --python 3.12 --with 'aiohttp>=3.12,<4' --with pytest \
  python -m pytest tests/test_android.py tests/test_tracking.py tests/test_usb.py tests/test_filter.py -q
```

Android instrumentation requires a running arm64 Android 13+ emulator or device.
JVM tests write generated robot programs and estimator packets into
`app/build/test-fixtures`; Python executes those exact programs against the same
frame-only/one-shot-gait test double as the iPhone code. Existing Swift integration
tests require `swift run --package-path ios PoseCoreChecks` first.

See [verification results](VERIFICATION.md) for the actual tested configuration,
checks performed, and remaining hardware limits. An emulator is not a Pixel camera:
[Google supports ARCore emulation only on x86/x86_64](https://developers.google.com/ar/develop/java/emulator),
so this Apple-silicon Mac's ARM emulator cannot validate live ARCore tracking.
Synthetic image tests exercise the APK's native OpenCV detector separately.

## Implementation notes

ARCore's unrotated physical camera pose and CPU-image intrinsics replace ARKit's.
The wire transforms remain row-major, metres, +Y up:
`world_from_tag = world_from_camera * diag(1,-1,-1,1) * cv_camera_from_tag`.
CPU luma copying respects row/pixel stride. Detection runs with one frame in flight
at up to 15 Hz. Camera pause/restart creates a new world session and clears poses.
No cloud anchors, depth API, ARCore API key, or cloud project is required.

The Kalman filter retains the six-state iPhone model (white acceleration PSD
0.0225 m²/s³, viewing-ray measurement covariance, 16.27 innovation gate, 1 s
prediction limit, 15 cm per-axis standard-deviation limit). Orientation is held
from the last accepted observation. Predictions never replace raw observation
freshness for automated movement. These are initial tuning values.

Stop disarms immediately and waits behind any in-flight HTTP submission before
VM-break. Motion completion requires matching robot log tokens; walking additionally
requires every cycle's frame count. Walk deadlines scale to 12–30 s; other motion
deadlines are 12 s. A failed Stop remains visibly unconfirmed. Android can kill an
app or lose Wi-Fi, so delivery is not guaranteed after process termination or link
loss. Keep motion batches finite and use the robot's physical controls if needed.

All robot traffic uses the physical robot's installed API, without modifying
firmware, calibration, startup scripts or files. Third-party notices are in
[THIRD-PARTY.md](THIRD-PARTY.md) and bundled in APK assets.
