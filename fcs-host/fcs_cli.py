from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from fcs_bridge import BridgeTransport, MspClient, discover_fc_capabilities
from fcs_bridge.blackbox_download import read_bridge_status, transfer_blackbox_log_from_bridge
from fcs_bridge.blackbox_transfer import erase_dataflash
from fcs_bridge.writeback import write_betaflight_cli_text_to_bridge


def _env_default(name: str, fallback: str) -> str:
    return os.environ.get(name, fallback)


def _print_json(payload: Any) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def _error(exc: BaseException, *, retryable: bool = True) -> dict[str, Any]:
    return {"error": {"kind": exc.__class__.__name__, "message": str(exc), "retryable": retryable}}


def _inspect(host: str, *, port: int, timeout_seconds: float) -> dict[str, Any]:
    with BridgeTransport(host, port, timeout_seconds=timeout_seconds) as transport:
        capabilities = discover_fc_capabilities(MspClient(transport), timeout_seconds=timeout_seconds)
    identity = capabilities.identity
    storage = capabilities.blackbox_storage
    return {
        "bridge_host": host,
        "bridge_port": port,
        "identity": {
            "fc_variant": identity.fc_variant,
            "fc_version": ".".join(str(part) for part in identity.fc_version),
            "msp_api": f"{identity.api_version[0]}.{identity.api_version[1]}",
        },
        "blackbox_storage": {
            "dataflash_available": storage.dataflash_available,
            "dataflash_supported": storage.dataflash_supported,
            "dataflash_ready": storage.dataflash_ready,
            "sector_count": storage.sector_count,
            "total_size": storage.total_size,
            "used_size": storage.used_size,
            "sdcard_summary_available": storage.sdcard_summary_available,
            "diagnostic": storage.diagnostic,
        },
    }


def _transfer_error_payload(exc: BaseException, *, output_path: Path) -> dict[str, Any]:
    payload = _error(exc, retryable=True)
    payload["error"].update({
        "output_path": str(output_path),
        "part_path": str(output_path.with_suffix(output_path.suffix + ".part")),
        "state_path": str(output_path.with_suffix(output_path.suffix + ".state.json")),
    })
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="FCS hardware CLI for flight-controller operations")
    sub = parser.add_subparsers(dest="area", required=True)

    inspect = sub.add_parser("inspect")
    inspect.add_argument("--bridge-host", default=_env_default("FCS_BRIDGE_HOST", "tuna-bridge-usb"), help="FCS Bridge host (default: $FCS_BRIDGE_HOST or tuna-bridge-usb)")
    inspect.add_argument("--port", type=int, default=5761)
    inspect.add_argument("--timeout", type=float, default=2.5)
    inspect.add_argument("--json", action="store_true")

    status = sub.add_parser("status")
    status.add_argument("--bridge-host", default=_env_default("FCS_BRIDGE_HOST", "tuna-bridge-usb"), help="FCS Bridge host (default: $FCS_BRIDGE_HOST or tuna-bridge-usb)")
    status.add_argument("--timeout", type=float, default=8.0)
    status.add_argument("--json", action="store_true")

    blackbox = sub.add_parser("blackbox")
    blackbox_sub = blackbox.add_subparsers(dest="action", required=True)
    transfer = blackbox_sub.add_parser("transfer")
    transfer.add_argument("--bridge-host", default=_env_default("FCS_BRIDGE_HOST", "tuna-bridge-usb"), help="FCS Bridge host (default: $FCS_BRIDGE_HOST or tuna-bridge-usb)")
    transfer.add_argument("--output", required=True)
    transfer.add_argument("--size", type=int)
    transfer.add_argument("--timeout", type=float, default=60.0)
    transfer.add_argument("--chunk-size", type=int, default=1024 * 1024)
    transfer.add_argument("--max-attempts", type=int, default=3)
    transfer.add_argument("--no-trigger-msc", action="store_true")
    transfer.add_argument("--no-resume", action="store_true")
    transfer.add_argument("--progress", action="store_true")
    transfer.add_argument("--json", action="store_true")
    erase = blackbox_sub.add_parser("erase")
    erase.add_argument("--bridge-host", default=_env_default("FCS_BRIDGE_HOST", "tuna-bridge-usb"), help="FCS Bridge host (default: $FCS_BRIDGE_HOST or tuna-bridge-usb)")
    erase.add_argument("--port", type=int, default=5761)
    erase.add_argument("--timeout", type=float, default=5.0)
    erase.add_argument("--confirm", required=True)
    erase.add_argument("--json", action="store_true")

    cli = sub.add_parser("cli")
    cli_sub = cli.add_subparsers(dest="action", required=True)
    write = cli_sub.add_parser("write")
    write.add_argument("--bridge-host", default=_env_default("FCS_BRIDGE_HOST", "tuna-bridge-usb"), help="FCS Bridge host (default: $FCS_BRIDGE_HOST or tuna-bridge-usb)")
    write.add_argument("--port", type=int, default=5761)
    write.add_argument("--timeout", type=float, default=5.0)
    write_source = write.add_mutually_exclusive_group(required=True)
    write_source.add_argument("--command")
    write_source.add_argument("--cli-file")
    write.add_argument("--confirm", required=True)
    write.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)
    try:
        if args.area == "inspect":
            payload = _inspect(args.bridge_host, port=args.port, timeout_seconds=args.timeout)
        elif args.area == "status":
            bridge_status = read_bridge_status(args.bridge_host, timeout_seconds=args.timeout)
            payload = {
                "bridge_host": args.bridge_host,
                "status_text": bridge_status.text,
                "usb_cdc_connected": bridge_status.usb_cdc_connected,
                "msc_raw_ready": bridge_status.msc_raw_ready,
                "msc_mounted": bridge_status.msc_mounted,
            }
        elif args.area == "blackbox" and args.action == "transfer":
            def progress(event: dict[str, object]) -> None:
                print(
                    f"raw={event['raw_bytes_downloaded']}/{event['requested_size']} "
                    f"written={event['written_bytes']} retries={event['retries']}",
                    file=sys.stderr,
                )
            output_path = Path(args.output)
            payload = transfer_blackbox_log_from_bridge(
                args.bridge_host,
                output_path=output_path,
                size=args.size,
                trigger_msc=not args.no_trigger_msc,
                timeout_seconds=args.timeout,
                resume=not args.no_resume,
                chunk_size=args.chunk_size,
                max_attempts=args.max_attempts,
                progress=progress if args.progress else None,
            )
        elif args.area == "blackbox" and args.action == "erase":
            if args.confirm != "erase-transferred-blackbox-log":
                raise ValueError("confirmation must be erase-transferred-blackbox-log")
            with BridgeTransport(args.bridge_host, args.port, timeout_seconds=args.timeout) as transport:
                erase_dataflash(MspClient(transport), timeout_seconds=args.timeout)
            payload = {"bridge_host": args.bridge_host, "erased": True}
        elif args.area == "cli" and args.action == "write":
            if args.confirm != "write-fc-cli":
                raise ValueError("confirmation must be write-fc-cli")
            cli_text = args.command if args.command is not None else Path(args.cli_file).read_text()
            result = write_betaflight_cli_text_to_bridge(args.bridge_host, args.port, cli_text, timeout_seconds=args.timeout)
            payload = {"bridge_host": args.bridge_host, "success": result.success, "transcript": result.transcript}
            if not result.success:
                _print_json(payload)
                return 1
        else:
            return 2
    except (OSError, RuntimeError, TimeoutError, ValueError) as exc:
        payload = _transfer_error_payload(exc, output_path=Path(args.output)) if getattr(args, "area", None) == "blackbox" and getattr(args, "action", None) == "transfer" else _error(exc)
        if getattr(args, "json", False):
            _print_json(payload)
        else:
            print(payload["error"]["message"], file=sys.stderr)
        return 1

    if getattr(args, "json", False):
        _print_json(payload)
    else:
        print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
