"""KT2 HTTP status and a fixed, non-motion Python probe. Does not flash firmware."""
import argparse
import ipaddress
import json
import time
import urllib.error
import urllib.parse
import urllib.request

PROBE = """import sys
print('KT2_PYTHON_PROBE_BEGIN')
print(sys.implementation)
print('q_available', 'q' in globals())
if 'q' in globals():
    print('q_methods', dir(q))
print('KT2_PYTHON_PROBE_END')
"""


def request(opener, url, body=None):
    data = urllib.parse.urlencode(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data)
    if data is not None:
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with opener.open(req, timeout=5) as response:
        return response.read(1024 * 1024).decode("utf-8", errors="replace")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["status", "probe-python"])
    parser.add_argument("--host", default="192.168.4.1", help="Robot's local IPv4 address")
    args = parser.parse_args()
    host = ipaddress.IPv4Address(args.host)
    if not host.is_private or host.is_loopback or host.is_unspecified or host.is_link_local or host.is_multicast:
        parser.error("Use the robot's private LAN/hotspot address")
    base = f"http://{host}"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        raw = request(opener, base + "/ping")
        print(raw)
        if args.command == "status":
            return
        # Confirm the expected model before submitting the fixed Python probe.
        identity = json.loads(raw)
        if "B4KT2" not in str(identity.get("model", "")) and "B4KT2" not in str(identity.get("v", "")):
            raise ValueError("Response does not identify a B4KT2; probe was not sent")
        result = request(opener, base + "/py", {"code": PROBE})
        print(result)
        if json.loads(result).get("status") != "OK":
            raise ValueError("Robot did not accept the probe")
        logs = ""
        for _ in range(10):
            time.sleep(0.5)
            chunk = request(opener, base + "/log")
            print(chunk, end="")
            logs += chunk
            if "KT2_PYTHON_PROBE_END" in logs:
                return
        raise ValueError("Probe submitted, but execution was not confirmed in the logs")
    except (urllib.error.URLError, OSError, ValueError) as exc:
        parser.exit(1, f"\nKT2: {exc}\nConnect to the robot's Wi-Fi or supply its LAN address with --host.\n")


if __name__ == "__main__":
    main()
