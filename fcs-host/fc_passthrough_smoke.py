#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys

from fcs_bridge import (
    BridgeConnectionError,
    BridgeTransport,
    MSP_API_VERSION,
    MSP_FC_VARIANT,
    MSP_FC_VERSION,
    MSP_IDENT,
    MspClient,
    MspProtocolError,
    parse_api_version,
    parse_fc_variant,
    parse_fc_version,
    parse_ident,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test FC MSP passthrough through the Tuna Bridge")
    parser.add_argument("host", help="Bridge hostname or IP")
    parser.add_argument("--port", type=int, default=5761)
    parser.add_argument("--timeout", type=float, default=2.5)
    args = parser.parse_args()

    try:
        with BridgeTransport(args.host, args.port, timeout_seconds=args.timeout) as transport:
            print(f"bridge connect ok host={args.host} port={args.port}")

            try:
                client = MspClient(transport)
                api = client.request(MSP_API_VERSION, timeout_seconds=args.timeout)
                protocol, major, minor = parse_api_version(api.payload)
                print(
                    f"msp api ok protocol={protocol} api={major}.{minor}"
                )

                variant = client.request(MSP_FC_VARIANT, timeout_seconds=args.timeout)
                print(f"msp fc-variant ok variant={parse_fc_variant(variant.payload)}")

                version = client.request(MSP_FC_VERSION, timeout_seconds=args.timeout)
                v_major, v_minor, v_patch = parse_fc_version(version.payload)
                print(f"msp fc-version ok version={v_major}.{v_minor}.{v_patch}")
                return 0
            except TimeoutError:
                print("msp api fail timeout waiting for FC response")
                print("msp fallback trying MSP_IDENT")
                ident = client.request(MSP_IDENT, timeout_seconds=args.timeout)
                info = parse_ident(ident.payload)
                print(
                    "msp ident ok"
                    f" version={info['version']}"
                    f" multitype={info['multitype']}"
                    f" msp_version={info['msp_version']}"
                    f" capability={info['capability']}"
                )
                return 0
    except (BridgeConnectionError, MspProtocolError, TimeoutError) as exc:
        print(f"smoke fail reason={exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
