#!/usr/bin/env python3
"""Fetch pinned official OpenCV and XcodeGen binaries; generate the Xcode project."""
import hashlib
from pathlib import Path
import subprocess
import urllib.request

ROOT = Path(__file__).resolve().parent
DEPENDENCIES = [
    ("Vendor", "opencv-4.13.0-ios-framework.zip",
     "https://github.com/opencv/opencv/releases/download/4.13.0/opencv-4.13.0-ios-framework.zip",
     "7ac1a77d21aa9556422e08d8b7ffcc30dfa9ebc0351a0ff32216395e8b14bede", "opencv2.framework"),
    (".tools", "xcodegen.zip",
     "https://github.com/yonaskolb/XcodeGen/releases/download/2.46.0/xcodegen.zip",
     "4d9e34b62172d645eed6457cac13fc222569974098ef4ee9c3368bedf0196806", "xcodegen/bin/xcodegen"),
]


def main():
    for folder, name, url, digest, extracted in DEPENDENCIES:
        directory = ROOT / folder
        directory.mkdir(parents=True, exist_ok=True)
        archive = directory / name
        if not archive.exists():
            print(f"Downloading {name}", flush=True)
            temporary = archive.with_suffix(".download")
            urllib.request.urlretrieve(url, temporary)
            temporary.replace(archive)
        actual = hashlib.file_digest(archive.open("rb"), "sha256").hexdigest()
        if actual != digest:
            raise SystemExit(f"Checksum mismatch for {archive}; remove it and retry.")
        if not (directory / extracted).exists():
            subprocess.run(["ditto", "-x", "-k", str(archive), str(directory)], check=True)
        print(f"Verified {name}", flush=True)
    generator = ROOT / ".tools/xcodegen/bin/xcodegen"
    generator.chmod(generator.stat().st_mode | 0o111)
    subprocess.run([str(generator), "generate", "--spec", str(ROOT / "project.yml")], cwd=ROOT, check=True)
    print(f"Open {ROOT / 'KT2Pose.xcodeproj'} in Xcode. Select your signing team and physical iPhone.")


if __name__ == "__main__":
    main()
