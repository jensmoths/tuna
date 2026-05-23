#!/usr/bin/env python3
from __future__ import annotations

import argparse
import binascii
import string
import sys
import time

from fcs_bridge import BridgeConnectionError, BridgeTransport, build_msp_v1_request


def hexdump(data: bytes) -> str:
    lines: list[str] = []
    for offset in range(0, len(data), 16):
        chunk = data[offset : offset + 16]
        hex_part = " ".join(f"{b:02x}" for b in chunk)
        ascii_part = "".join(chr(b) if chr(b) in string.printable and b >= 32 else "." for b in chunk)
        lines.append(f"{offset:04x}  {hex_part:<47}  {ascii_part}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Raw byte probe through the Tuna Bridge")
    parser.add_argument("host", help="Bridge hostname or IP")
    parser.add_argument("--port", type=int, default=5761)
    parser.add_argument("--timeout", type=float, default=2.5)
    parser.add_argument("--read-seconds", type=float, default=2.0)
    parser.add_argument("--hex", default="", help="raw bytes to send as hex")
    parser.add_argument(
        "--msp-api-version",
        action="store_true",
        help="send a zero-payload MSP_API_VERSION request",
    )
    args = parser.parse_args()

    payload = b""
    if args.hex:
        payload += binascii.unhexlify(args.hex.replace(" ", ""))
    if args.msp_api_version:
        payload += build_msp_v1_request(1)

    try:
        with BridgeTransport(args.host, args.port, timeout_seconds=args.timeout) as transport:
            print(f"bridge connect ok host={args.host} port={args.port}")
            if payload:
                transport.send(payload)
                print(f"sent bytes len={len(payload)}")
                print(hexdump(payload))

            deadline = time.time() + args.read_seconds
            chunks: list[bytes] = []
            while time.time() < deadline:
                data = transport.recv(4096)
                if data:
                    chunks.append(data)
                else:
                    time.sleep(0.05)

            received = b"".join(chunks)
            if received:
                print(f"recv bytes len={len(received)}")
                print(hexdump(received))
                return 0

            print("recv bytes len=0")
            return 1
    except (BridgeConnectionError, binascii.Error) as exc:
        print(f"probe fail reason={exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
