"""Capture serial output without sending application bytes.

Opening this KT2's USB port was observed to reboot it even with DTR/RTS false.
This is not a reset-free capture method on this hardware.
"""
import argparse
from datetime import datetime, timezone
from pathlib import Path
import time

import serial

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--port", default="/dev/cu.usbmodem1101")
parser.add_argument("--seconds", type=float, default=10)
parser.add_argument("--baud", type=int, default=115200)
args = parser.parse_args()
out = Path("evidence")
out.mkdir(exist_ok=True, mode=0o700)
stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
path = out / f"serial-{stamp}.bin"
port = serial.Serial(port=None, baudrate=args.baud, timeout=0.2, exclusive=True)
port.dtr = False
port.rts = False
port.port = args.port
data = bytearray()
try:
    port.open()
    deadline = time.monotonic() + args.seconds
    while time.monotonic() < deadline and len(data) < 1024 * 1024:
        data.extend(port.read(min(max(port.in_waiting, 1), 4096)))
finally:
    port.close()
    path.write_bytes(data)
    path.with_suffix(".txt").write_text(data.decode("utf-8", errors="replace"))
print(f"Captured {len(data)} bytes to {path}")
# Raw captures may contain device settings. Inspect locally before sharing.
