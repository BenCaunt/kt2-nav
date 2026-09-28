"""Analyze a saved KT2 ESP32 flash dump; never connects to the robot."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import struct


def analyze(source, output):
    data = source.read_bytes()
    output.mkdir(parents=True, exist_ok=True)
    report = {"source": str(source), "size": len(data),
              "sha256": hashlib.sha256(data).hexdigest(), "partitions": []}
    table = data[0x8000:0x9000]
    for i in range(0, len(table), 32):
        if table[i:i + 2] == b"\xeb\xeb":
            report["partition_table_md5_valid"] = (
                hashlib.md5(table[:i]).digest() == table[i + 16:i + 32])
            break
        if table[i:i + 2] != b"\xaa\x50":
            break
        _, kind, subtype, offset, size, name, flags = struct.unpack_from("<HBBII16sI", table, i)
        label = name.rstrip(b"\0").decode("ascii")
        if not re.fullmatch(r"[A-Za-z0-9_-]+", label) or offset + size > len(data):
            raise ValueError("Invalid partition entry")
        blob = data[offset:offset + size]
        (output / f"{label}.bin").write_bytes(blob)
        report["partitions"].append(dict(name=label, type=kind, subtype=subtype,
            offset=offset, size=size, flags=flags, erased=all(x == 255 for x in blob)))

    # Firmware includes a ROM resource table: {name pointer, start pointer, end pointer}.
    # Resolve pointers using the ESP image's own segment headers.
    app = next(p for p in report["partitions"]
               if p["type"] == 0 and data[p["offset"]] == 0xE9)
    base = app["offset"]
    segments = []
    cursor = base + 24
    for _ in range(data[base + 1]):
        address, length = struct.unpack_from("<II", data, cursor)
        cursor += 8
        if cursor + length > base + app["size"]:
            raise ValueError("Invalid image segment")
        segments.append((address, cursor, length))
        cursor += length

    def resolve(pointer, end=False):
        for address, offset, size in segments:
            if address <= pointer < address + size or (end and pointer == address + size):
                return offset + pointer - address
        return None

    anchor = data.index(b"/sys/web/999.html\0", base, base + app["size"])
    anchor_address = next(address + anchor - offset for address, offset, size in segments
                          if offset <= anchor < offset + size)
    candidates = [m.start() for m in re.finditer(re.escape(struct.pack("<I", anchor_address)), data)]
    resources = []
    for table_start in candidates:
        entries = []
        for cursor in range(table_start, min(len(data) - 11, table_start + 65536), 12):
            name_ptr, start_ptr, end_ptr = struct.unpack_from("<III", data, cursor)
            name_off, start, end = resolve(name_ptr), resolve(start_ptr), resolve(end_ptr, True)
            if name_off is None:
                break
            name = data[name_off:name_off + 256].split(b"\0", 1)[0].decode("ascii", errors="replace")
            path = PurePosixPath(name)
            if not name.startswith("/sys/") or ".." in path.parts or "\\" in name:
                break
            if start_ptr == end_ptr == 0:
                blob = b""
            elif None not in (start, end) and start < end:
                blob = data[start:end]
            else:
                break
            target = output / "resources" / name.lstrip("/")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(blob)
            decoded = None
            if blob[:2] == b"\x1f\x8b":
                decoded = gzip.decompress(blob)  # Validates gzip integrity.
                target.with_suffix("").write_bytes(decoded)
            entries.append(dict(path=name, table_offset=cursor, offset=start,
                                size=len(blob), decoded_size=len(decoded) if decoded is not None else None,
                                sha256=hashlib.sha256(blob).hexdigest()))
        if len(entries) > len(resources):
            resources = entries
    report["resources"] = resources
    (output / "manifest.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"sha256": report["sha256"], "size": len(data),
                      "partition_table_md5_valid": report.get("partition_table_md5_valid"),
                      "partitions": report["partitions"], "resource_count": len(resources)}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dump", type=Path)
    parser.add_argument("--output", type=Path, default=Path("evidence/analysis"))
    args = parser.parse_args()
    analyze(args.dump, args.output)
