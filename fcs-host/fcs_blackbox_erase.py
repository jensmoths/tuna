#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys

from fcs_bridge import (
    BridgeConnectionError,
    BridgeTransport,
    MspClient,
    discover_fc_capabilities,
    erase_dataflash,
    get_blackbox_log_storage_status,
)


CONFIRM_TEXT = "erase-transferred-blackbox-log"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Erase transferred Blackbox Log storage on the FC through FCS/MSP"
    )
    parser.add_argument("host", help="Bridge hostname or IP")
    parser.add_argument("--port", type=int, default=5761)
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--msp-version", type=int, choices=(1, 2), default=1)
    parser.add_argument(
        "--confirm",
        required=True,
        help=f"must be exactly {CONFIRM_TEXT!r}; erase only after validated transfer/import",
    )
    args = parser.parse_args()

    if args.confirm != CONFIRM_TEXT:
        print(f"erase fail reason=confirmation must be exactly {CONFIRM_TEXT!r}")
        return 2

    try:
        with BridgeTransport(args.host, args.port, timeout_seconds=args.timeout) as transport:
            client = MspClient(transport)
            before = discover_fc_capabilities(client, timeout_seconds=args.timeout).blackbox_storage
            if not before.dataflash_available:
                print(f"erase fail reason={before.diagnostic}")
                return 1
            if not before.dataflash_ready:
                print("erase fail reason=dataflash is not ready")
                return 1
            if before.used_size == 0:
                print(
                    "erase ok already_empty=1"
                    f" before_used_bytes={before.used_size}"
                    f" after_used_bytes={before.used_size}"
                    f" total_size={before.total_size}"
                )
                return 0

            try:
                erase_dataflash(client, timeout_seconds=args.timeout, msp_version=args.msp_version)
                after = get_blackbox_log_storage_status(client, timeout_seconds=args.timeout)
            except TimeoutError:
                transport.disconnect()
                with BridgeTransport(args.host, args.port, timeout_seconds=args.timeout) as retry_transport:
                    after = get_blackbox_log_storage_status(
                        MspClient(retry_transport), timeout_seconds=args.timeout
                    )
                if after.used_size != 0:
                    raise

        print(
            "erase ok"
            f" before_used_bytes={before.used_size}"
            f" after_used_bytes={after.used_size}"
            f" total_size={after.total_size}"
        )
        return 0
    except (BridgeConnectionError, TimeoutError, RuntimeError, ValueError, OSError) as exc:
        print(f"erase fail reason={exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
