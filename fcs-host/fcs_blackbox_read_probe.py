#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import string
import sys
from pathlib import Path

from fcs_bridge import BridgeConnectionError, BridgeTransport, MspClient, read_dataflash_range


def hexdump(data: bytes) -> str:
    lines: list[str] = []
    for offset in range(0, len(data), 16):
        chunk = data[offset : offset + 16]
        hex_part = " ".join(f"{byte:02x}" for byte in chunk)
        ascii_part = "".join(
            chr(byte) if chr(byte) in string.printable and byte >= 32 else "."
            for byte in chunk
        )
        lines.append(f"{offset:04x}  {hex_part:<47}  {ascii_part}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read a small Blackbox Log dataflash range as a Host Computer diagnostic artifact"
    )
    parser.add_argument("host", help="Bridge hostname or IP")
    parser.add_argument("--port", type=int, default=5761)
    parser.add_argument("--timeout", type=float, default=2.5)
    parser.add_argument("--address", type=int, default=0)
    parser.add_argument("--size", type=int, default=1024)
    parser.add_argument("--msp-version", type=int, choices=(1, 2), default=2)
    parser.add_argument("--chunk-size", type=int, default=512)
    parser.add_argument("--output-dir", default="transferred-logs")
    args = parser.parse_args()

    try:
        with BridgeTransport(args.host, args.port, timeout_seconds=args.timeout) as transport:
            data = read_dataflash_range(
                MspClient(transport),
                address=args.address,
                size=args.size,
                timeout_seconds=args.timeout,
                chunk_size=args.chunk_size,
                msp_version=args.msp_version,
            )
    except (BridgeConnectionError, TimeoutError, RuntimeError, ValueError) as exc:
        print(f"read fail reason={exc}")
        return 1

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = dt.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    path = output_dir / f"probe-dataflash-{args.address:08x}-{len(data)}-{timestamp}.bbl"
    path.write_bytes(data)

    print(f"read ok address={args.address} requested={args.size} received={len(data)} path={path}")
    preview = data[:128]
    if preview.startswith(b"H Product:Blackbox"):
        print("blackbox-header=present")
    else:
        print("blackbox-header=not-at-start")
    if preview:
        print(hexdump(preview))
    return 0


if __name__ == "__main__":
    sys.exit(main())
