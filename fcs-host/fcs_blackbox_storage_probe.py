#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys

from fcs_bridge import (
    BridgeConnectionError,
    BridgeTransport,
    MspClient,
    MspProtocolError,
    discover_fc_capabilities,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read-only FCS Blackbox Log storage discovery through the Tuna Bridge"
    )
    parser.add_argument("host", help="Bridge hostname or IP")
    parser.add_argument("--port", type=int, default=5761)
    parser.add_argument("--timeout", type=float, default=2.5)
    args = parser.parse_args()

    try:
        with BridgeTransport(args.host, args.port, timeout_seconds=args.timeout) as transport:
            capabilities = discover_fc_capabilities(
                MspClient(transport), timeout_seconds=args.timeout
            )

        identity = capabilities.identity
        storage = capabilities.blackbox_storage
        print(
            "fc ok"
            f" variant={identity.fc_variant}"
            f" version={'.'.join(str(part) for part in identity.fc_version)}"
            f" msp_api={identity.api_version[0]}.{identity.api_version[1]}"
        )
        print(
            "blackbox-storage"
            f" dataflash_available={int(storage.dataflash_available)}"
            f" dataflash_supported={int(storage.dataflash_supported)}"
            f" dataflash_ready={int(storage.dataflash_ready)}"
            f" sector_count={storage.sector_count}"
            f" total_size={storage.total_size}"
            f" used_size={storage.used_size}"
            f" sdcard_summary_available={int(storage.sdcard_summary_available)}"
        )
        if storage.diagnostic:
            print(f"diagnostic={storage.diagnostic}")
        return 0
    except (BridgeConnectionError, MspProtocolError, TimeoutError) as exc:
        print(f"probe fail reason={exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
