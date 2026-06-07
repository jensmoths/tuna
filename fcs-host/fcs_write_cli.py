#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from fcs_bridge import BridgeConnectionError, write_betaflight_cli_text_to_bridge


CONFIRM_TEXT = "write-fc-cli"


def _read_cli_text(args: argparse.Namespace) -> str:
    if args.cli_file is not None:
        if args.cli_file == "-":
            return sys.stdin.read()
        return Path(args.cli_file).read_text()
    return "\n".join(args.command or [])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Write Betaflight CLI text to the FC through FCS/Bridge"
    )
    parser.add_argument("host", help="Bridge hostname or IP")
    parser.add_argument("--port", type=int, default=5761)
    parser.add_argument("--timeout", type=float, default=5.0)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--command",
        action="append",
        help="Betaflight CLI command; may be repeated and is sent in order",
    )
    source.add_argument("--cli-file", help="file containing Betaflight CLI text, or '-' for stdin")
    parser.add_argument(
        "--confirm",
        required=True,
        help=f"must be exactly {CONFIRM_TEXT!r}; use only after Operator approval when applying Tune Updates",
    )
    parser.add_argument(
        "--no-transcript",
        action="store_true",
        help="suppress FC CLI transcript output",
    )
    args = parser.parse_args(argv)

    if args.confirm != CONFIRM_TEXT:
        print(f"write fail reason=confirmation must be exactly {CONFIRM_TEXT!r}")
        return 2

    try:
        cli_text = _read_cli_text(args)
        result = write_betaflight_cli_text_to_bridge(
            args.host,
            args.port,
            cli_text,
            timeout_seconds=args.timeout,
        )
    except (BridgeConnectionError, OSError, RuntimeError, ValueError, UnicodeError) as exc:
        print(f"write fail reason={exc}")
        return 1

    status = "ok" if result.success else "fail"
    print(f"write {status} transcript_bytes={len(result.transcript.encode('latin1', errors='replace'))}")
    if not args.no_transcript:
        print("--- transcript ---")
        print(result.transcript, end="" if result.transcript.endswith("\n") else "\n")
    return 0 if result.success else 1


if __name__ == "__main__":
    sys.exit(main())
