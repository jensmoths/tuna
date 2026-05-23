#!/usr/bin/env python3
from __future__ import annotations

import argparse
import socket
import sys
import time

from fcs_bridge import BridgeConnectionError, BridgeTransport, probe_single_client_behavior


def main() -> int:
    parser = argparse.ArgumentParser(
        description="FCS connectivity tracer for the Tuna Bridge"
    )
    parser.add_argument("host", help="Bridge hostname or IP")
    parser.add_argument("--port", type=int, default=5761, help="Bridge TCP port")
    parser.add_argument(
        "--timeout",
        type=float,
        default=3.0,
        help="socket timeout in seconds",
    )
    parser.add_argument(
        "--hold-seconds",
        type=float,
        default=1.0,
        help="how long to keep the first connection open",
    )
    parser.add_argument(
        "--probe-single-client",
        action="store_true",
        help="attempt a second connection while the first is open",
    )
    args = parser.parse_args()

    try:
        resolved_ip = socket.gethostbyname(args.host)
        print(f"resolve ok host={args.host} ip={resolved_ip}")
    except OSError as exc:
        print(f"resolve fail host={args.host} reason={exc}")
        return 1

    try:
        started = time.time()
        with BridgeTransport(args.host, args.port, timeout_seconds=args.timeout) as transport:
            elapsed = time.time() - started
            print(f"connect ok host={args.host} port={args.port} elapsed_s={elapsed:.3f}")
            time.sleep(args.hold_seconds)

            if args.probe_single_client:
                result = probe_single_client_behavior(
                    args.host,
                    args.port,
                    timeout_seconds=args.timeout,
                )
                print(
                    "single-client"
                    f" first_connected={int(result.first_connected)}"
                    f" second_connected={int(result.second_connected)}"
                    f" second_rejected={int(result.second_rejected)}"
                    f" detail={result.detail}"
                )

        print("disconnect ok")
        return 0
    except BridgeConnectionError as exc:
        print(f"connect fail reason={exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
