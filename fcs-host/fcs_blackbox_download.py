#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import sys
import time
from pathlib import Path

from fcs_bridge import (
    BridgeConnectionError,
    BridgeTransport,
    MspClient,
    discover_fc_capabilities,
    read_dataflash_range,
)


def _default_output_path(output_dir: Path) -> Path:
    timestamp = dt.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    return output_dir / f"blackbox-{timestamp}.bbl"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download a complete Blackbox Log dataflash image through the Tuna Bridge"
    )
    parser.add_argument("host", help="Bridge hostname or IP")
    parser.add_argument("--port", type=int, default=5761)
    parser.add_argument("--timeout", type=float, default=2.5)
    parser.add_argument("--output-dir", default="transferred-logs")
    parser.add_argument("--output", help="specific .bbl output path")
    parser.add_argument(
        "--size",
        type=int,
        default=None,
        help="bytes to download; defaults to FC-reported used dataflash size",
    )
    parser.add_argument(
        "--progress-bytes",
        type=int,
        default=262144,
        help="print progress after this many newly downloaded bytes",
    )
    parser.add_argument("--msp-version", type=int, choices=(1, 2), default=2)
    parser.add_argument("--chunk-size", type=int, default=512)
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = Path(args.output) if args.output else _default_output_path(output_dir)
    partial_path = output_path.with_suffix(output_path.suffix + ".part")

    started = time.time()
    downloaded = 0
    next_progress = args.progress_bytes

    try:
        with BridgeTransport(args.host, args.port, timeout_seconds=args.timeout) as transport:
            client = MspClient(transport)
            capabilities = discover_fc_capabilities(client, timeout_seconds=args.timeout)
            storage = capabilities.blackbox_storage
            if not storage.dataflash_available:
                print(f"download fail reason={storage.diagnostic}")
                return 1
            if not storage.dataflash_ready:
                print("download fail reason=dataflash is not ready")
                return 1

            total_size = args.size if args.size is not None else storage.used_size
            if total_size <= 0:
                print("download fail reason=FC reports no Blackbox Log dataflash bytes used")
                return 1

            print(
                "download start"
                f" variant={capabilities.identity.fc_variant}"
                f" version={'.'.join(str(part) for part in capabilities.identity.fc_version)}"
                f" bytes={total_size}"
                f" path={output_path}"
            )

            with partial_path.open("wb") as out:
                while downloaded < total_size:
                    requested = min(args.progress_bytes, total_size - downloaded)
                    data = read_dataflash_range(
                        client,
                        address=downloaded,
                        size=requested,
                        timeout_seconds=args.timeout,
                        chunk_size=args.chunk_size,
                        msp_version=args.msp_version,
                    )
                    if not data:
                        print(
                            f"download fail reason=short read at address {downloaded}; kept partial={partial_path}"
                        )
                        return 1

                    out.write(data)
                    downloaded += len(data)

                    if downloaded >= next_progress or downloaded == total_size:
                        elapsed = max(time.time() - started, 0.001)
                        pct = downloaded * 100.0 / total_size
                        rate = downloaded / elapsed
                        print(
                            f"progress bytes={downloaded}/{total_size} pct={pct:.1f} rate_Bps={rate:.0f}",
                            flush=True,
                        )
                        while next_progress <= downloaded:
                            next_progress += args.progress_bytes

        partial_path.replace(output_path)
        elapsed = max(time.time() - started, 0.001)
        print(
            f"download ok bytes={downloaded} elapsed_s={elapsed:.1f} rate_Bps={downloaded / elapsed:.0f} path={output_path}"
        )
        return 0
    except (BridgeConnectionError, TimeoutError, RuntimeError, ValueError, OSError) as exc:
        print(f"download fail reason={exc}; kept partial={partial_path}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
