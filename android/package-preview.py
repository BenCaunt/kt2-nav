"""Create a shareable tester kit from an allowlist; no private research or signing files."""
from pathlib import Path
import hashlib
import shutil
import zipfile

ANDROID = Path(__file__).resolve().parent
ROOT = ANDROID.parent
OUTPUT = ROOT / 'artifacts/kt2-android'
APK_NAME = 'KT2-Pose-0.1.0-preview.apk'


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    apk = ANDROID / 'app/build/outputs/apk/release/app-release.apk'
    if not apk.is_file():
        raise SystemExit('Run android/build-preview.sh first')
    shutil.copy2(apk, OUTPUT / APK_NAME)
    shutil.copy2(ANDROID / 'TESTER-START-HERE.md', OUTPUT / 'START-HERE.md')
    archive = OUTPUT / 'KT2-Pose-Android-preview-kit.zip'
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as z:
        z.write(apk, APK_NAME)
        z.write(ANDROID / 'TESTER-START-HERE.md', 'START-HERE.md')
        z.write(ANDROID / 'THIRD-PARTY.md', 'THIRD-PARTY.md')
        z.write(ROOT / 'Start KT2 Android.command', 'desktop/Start KT2 Android.command')
        z.writestr('desktop/requirements.txt', 'aiohttp>=3.12,<4\n')
        for name in ['__init__.py', '__main__.py', 'protocol.py', 'receiver.py', 'usb.py', 'web/index.html']:
            z.write(ROOT / 'kt2_tracking' / name, 'desktop/kt2_tracking/' + name)
        for license_file in sorted((ANDROID / 'app/src/main/assets/licenses').rglob('*')):
            if license_file.is_file():
                z.write(license_file, 'licenses/' + str(license_file.relative_to(ANDROID / 'app/src/main/assets/licenses')))
    sums = []
    for artifact in [OUTPUT / APK_NAME, archive]:
        sums.append(hashlib.sha256(artifact.read_bytes()).hexdigest() + '  ' + artifact.name)
        print(f'{artifact} ({artifact.stat().st_size / 1048576:.1f} MiB)')
    (OUTPUT / 'SHA256SUMS.txt').write_text('\n'.join(sums) + '\n')


if __name__ == '__main__':
    main()
