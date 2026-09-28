# Android preview verification — 28 September 2026

This is a **hardware-unverified community preview**, not a claim of physical
Pixel 7 Pro compatibility testing. No physical robot was moved during this port.

## Passed

- Release APK compiled and signed with the local KT2 preview certificate;
  `apksigner verify` and ZIP alignment checks pass. Package `com.bencaunt.kt2pose`,
  version `0.1.0-preview` / code 1, minimum API 33, target API 35, arm64-v8a.
  The release is not debuggable. Tests use standard 4 KB memory pages. OpenCV's
  bundled `libc++_shared.so` has 4 KB ELF alignment, so 16 KB page-size devices
  are outside this preview's verified target.
- **17 JVM tests:** physical identity rejection, integer bounds, capability
  gating, coordinate conversion, filter velocity/prediction/outliers/world resets,
  duplicate frames/covariance, generated-program export, explicit arming, no
  queued motion, Stop after a delayed POST, missing walk confirmation, background/
  USB disarming, failed Stop, pairing rejection, leases, repeated commands,
  heartbeat expiry, and oversized messages.
- **3 Android native tests** on an ARM64 Android 15 emulator with the Pixel 7 Pro
  display profile: packaged OpenCV detects a perspective-warped marker, recovers
  known translation within 6 mm depth / 2 mm lateral tolerance, rejects duplicate,
  missing and too-small tags, and reads padded/interleaved luma correctly.
- **35 Python tests** across Android additions and the existing tracking/USB/filter
  suites: execute the Android-generated walking programs against the iPhone's
  frame-only, one-shot gait test double, including fast and blocking playback;
  verify empty-gait errors, estimator wire compatibility/expiry, adb forwarding
  ownership/recreation/cleanup, and existing iPhone/desktop regressions.
- Final signed APK installed and launched in the emulator. Desktop receiver
  connected through actual adb forwarding and the pairing code shown in the UI.
  `/api/state` and Stop acknowledgement worked; disarmed movement was rejected.
  Backgrounding disconnected the link; reopening reconnected while disarmed.
  Removing the adb forward was recovered, and receiver shutdown cleaned it up.
- Camera permission denial was exercised in the emulator, followed by granting
  permission and trying Start camera. Both denied permission and unavailable AR
  showed a recoverable message, with manual controls and pinned Stop retained.
- Release lint completed with no errors. Remaining warnings concern the deliberate
  portrait/ARM-only preview, pinned dependency versions, English UI strings,
  and backup configuration.
- The tester ZIP passes integrity checks and contains only allowlisted app,
  receiver, instructions, and license files. No private firmware research,
  recordings, device credentials or signing key are included.

## Dependency choice

Android uses OpenCV **4.11.0**, not the iPhone's 4.13.0. The 4.13.0 Android AAR
crashed in KleidiCV's SVE code on this Apple-silicon ARM emulator, whose reported
CPU capabilities included SVE2 without usable SVE. 4.11.0 passes the native tests
with its packaged library. A 4.12.0 trial also crashed in the native vision test.
This does **not** establish that those versions fail on real Pixel hardware.
No binary patches or CPU-feature workarounds are shipped.

## Still needs the tester's Pixel and KT2

- Live ARCore install/startup, camera permission behavior on that Android build,
  intrinsics, focus, preview/axis registration, frame rate, heat and battery use.
- Tag scale against a ruler and world stability when moving the phone around a
  stationary robot; filter and uncertainty tuning against real measurements.
- Wi-Fi routing to the robot while cellular is active and the hotspot has no
  internet, firmware capability discovery, physical gait/turn/posture operation,
  and Stop delivery on the tester's network.
- Actual USB cable disconnect/reconnect on a Pixel; Windows/Linux desktop hosts.
- Android 13/14/16+ device execution. Only the Android 15 emulator was run locally.

ARCore's supported-device list includes Pixel 7 Pro, but
[ARCore emulator tracking supports x86/x86_64 only](https://developers.google.com/ar/develop/java/emulator).
This Mac's ARM emulator cannot validate the live ARCore camera pipeline. The native
synthetic vision test is separate from ARCore and is not a substitute for it.

## Reproduce

```sh
android/build-preview.sh
android/gradlew -p android connectedDebugAndroidTest
uv run --no-project --managed-python --python 3.12 --with 'aiohttp>=3.12,<4' --with pytest \
  python -m pytest tests/test_android.py tests/test_tracking.py tests/test_usb.py tests/test_filter.py -q
adb -s emulator-5554 install -r artifacts/kt2-android/KT2-Pose-0.1.0-preview.apk
uv run --no-project --managed-python --python 3.12 --with 'aiohttp>=3.12,<4' \
  python android/smoke-emulator.py --serial emulator-5554
```

Native tests use the Android debug test signature; the shareable APK uses the
separate preview certificate. Uninstall only this app from your disposable emulator
when switching between those signatures. Instrumentation may uninstall the tested
app afterward; reinstall the release before the black-box smoke check. Do not
uninstall a real tester's app just to run these checks.

Generated test reports live under `android/app/build/reports/`; local build/tool
logs and screenshots are under the ignored `android/.tools/` directory. APK and
kit SHA-256 values are generated in `artifacts/kt2-android/SHA256SUMS.txt`.
