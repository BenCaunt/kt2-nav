import argparse
from datetime import datetime
from pathlib import Path
import secrets
import socket

from aiohttp import web

from .receiver import PoseStore, create_app
from .usb import AndroidUSBBridge, USBBridge


def local_addresses():
    addresses = set()
    try:
        addresses.update(x[4][0] for x in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET))
    except OSError:
        pass
    # UDP connect chooses a route without transmitting any packet.
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        try:
            sock.connect(("192.0.2.1", 9))
            addresses.add(sock.getsockname()[0])
        except OSError:
            pass
    return sorted(x for x in addresses if not x.startswith("127."))


def main():
    parser = argparse.ArgumentParser(description="Receive KT2 phone camera + ArUco poses")
    parser.add_argument("--host", help="Bind address; USB mode always uses loopback")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--token", help="Pairing code; generated if omitted")
    transport = parser.add_mutually_exclusive_group()
    transport.add_argument("--usb", action="store_true", help="Connect to the iPhone through USB instead of Wi-Fi")
    transport.add_argument("--android", action="store_true", help="Connect to Android through USB debugging / adb")
    parser.add_argument("--usb-port", type=int, default=8767, help="Mac loopback port for the USB tunnel")
    parser.add_argument("--device", help="iPhone UDID or Android adb serial when several devices are attached")
    parser.add_argument("--record", nargs="?", const="auto", type=str, help="Append JSONL observations (default: recordings/timestamp.jsonl)")
    args = parser.parse_args()
    usb_mode = args.usb or args.android
    if usb_mode and not args.token:
        parser.error("USB mode needs --token with the pairing code displayed by KT2 Pose")
    token = args.token or secrets.token_hex(4).upper()
    if not token.isascii() or not 8 <= len(token) <= 128:
        parser.error("Pairing code must contain 8-128 ASCII characters")
    record = args.record
    if record == "auto":
        record = f"recordings/kt2-{datetime.now():%Y%m%d-%H%M%S}.jsonl"
    if record:
        Path(record).parent.mkdir(parents=True, exist_ok=True)
    print("\nKT2 Pose receiver", flush=True)
    if usb_mode:
        print("  USB mode · phone joins robot Wi-Fi · computer keeps its internet connection", flush=True)
    else:
        for address in local_addresses():
            print(f"  iPhone Mac address: {address}:{args.port}", flush=True)
        print(f"  Pairing code: {token}", flush=True)
    print(f"  Dashboard: http://127.0.0.1:{args.port}", flush=True)
    print(f"  Recording: {record or 'off'}\n", flush=True)
    store = PoseStore(record=record)
    bridge_type = AndroidUSBBridge if args.android else USBBridge
    usb = bridge_type(token, store, port=args.usb_port, device=args.device) if usb_mode else None
    web.run_app(create_app(token, store, usb=usb), host="127.0.0.1" if usb_mode else args.host or "0.0.0.0", port=args.port, access_log=None)


if __name__ == "__main__":
    main()
