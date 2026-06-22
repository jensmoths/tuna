from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from . import analyze_csv_log, decode_blackbox_log, parse_blackbox_metadata, read_segment_rows
from .analysis_views import capture_plan_view, filter_evidence_view, noise_peak_view, pid_response_view, propwash_view, rpm_filter_view
from .metadata import metadata_summary


def _env_default(name: str, fallback: str) -> str:
    return os.environ.get(name, fallback)


def _print_json(payload: Any) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def _error(exc: BaseException) -> dict[str, Any]:
    return {"error": {"kind": exc.__class__.__name__, "message": str(exc), "retryable": False}}


def _write_json_file(path_text: str | None, payload: dict[str, Any]) -> str | None:
    if not path_text:
        return None
    path = Path(path_text)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return str(path)


def _concise_analysis(payload: dict[str, Any], *, csv_path: str | None = None, output_json_file: str | None = None) -> dict[str, Any]:
    result = {
        "row_count": payload.get("row_count"),
        "duration_seconds": payload.get("duration_seconds"),
        "quality": payload.get("quality"),
        "warnings": payload.get("warnings", []),
        "analysis_json_file": output_json_file,
    }
    if csv_path is not None:
        result["csv_path"] = csv_path
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Standalone Tuna Blackbox Log metadata, decode, and analysis CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    metadata = sub.add_parser("metadata")
    metadata.add_argument("path")
    metadata.add_argument("--full", action="store_true", help="include full parsed metadata in JSON output")
    metadata.add_argument("--metadata-json-file", help="write full metadata JSON to this file")
    metadata.add_argument("--json", action="store_true")

    decode = sub.add_parser("decode")
    decode.add_argument("path")
    decode.add_argument("--output", required=True, help="decoded CSV output path")
    decode.add_argument("--decoder-command", default=_env_default("TUNA_BLACKBOX_DECODER", "blackbox_decode"))
    decode.add_argument("--json", action="store_true")

    analyze = sub.add_parser("analyze")
    analyze.add_argument("csv_path")
    analyze.add_argument("--output-json-file", help="write full analysis JSON to this file")
    analyze.add_argument("--full-json", action="store_true", help="print full analysis JSON")
    analyze.add_argument("--json", action="store_true")

    decode_analyze = sub.add_parser("decode-analyze")
    decode_analyze.add_argument("path")
    decode_analyze.add_argument("--output", required=True, help="decoded CSV output path")
    decode_analyze.add_argument("--decoder-command", default=_env_default("TUNA_BLACKBOX_DECODER", "blackbox_decode"))
    decode_analyze.add_argument("--output-json-file", help="write full analysis JSON to this file")
    decode_analyze.add_argument("--full-json", action="store_true", help="print full analysis JSON")
    decode_analyze.add_argument("--json", action="store_true")

    rows = sub.add_parser("segment-rows")
    rows.add_argument("csv_path")
    rows.add_argument("--start-row", type=int, required=True)
    rows.add_argument("--end-row", type=int, required=True)
    rows.add_argument("--fields", help="comma-separated decoded CSV fields to return")
    rows.add_argument("--pad-rows", type=int, default=0)
    rows.add_argument("--json", action="store_true")

    for name in ("filter-evidence", "pid-response", "rpm-filter", "capture-plan"):
        view = sub.add_parser(name)
        view.add_argument("csv_path")
        view.add_argument("--json", action="store_true")
    for name in ("noise-peaks", "propwash"):
        view = sub.add_parser(name)
        view.add_argument("csv_path")
        view.add_argument("--limit", type=int, default=5)
        view.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)
    try:
        if args.command == "metadata":
            parsed = parse_blackbox_metadata(args.path)
            payload = {
                "path": args.path,
                "parse_status": parsed.parse_status,
                "metadata_summary": metadata_summary(parsed.metadata),
                "warnings": parsed.warnings,
            }
            metadata_file = _write_json_file(args.metadata_json_file, parsed.metadata)
            if metadata_file:
                payload["metadata_json_file"] = metadata_file
            if args.full:
                payload["metadata"] = parsed.metadata
        elif args.command == "decode":
            csv_path = decode_blackbox_log(args.path, args.output, decoder_command=args.decoder_command)
            payload = {"source_path": args.path, "csv_path": str(csv_path), "decoder_command": args.decoder_command}
        elif args.command == "analyze":
            analysis = analyze_csv_log(args.csv_path)
            output_json_file = _write_json_file(args.output_json_file, analysis)
            payload = analysis if args.full_json else _concise_analysis(analysis, csv_path=args.csv_path, output_json_file=output_json_file)
        elif args.command == "decode-analyze":
            csv_path = decode_blackbox_log(args.path, args.output, decoder_command=args.decoder_command)
            analysis = analyze_csv_log(csv_path)
            output_json_file = _write_json_file(args.output_json_file, analysis)
            payload = analysis if args.full_json else _concise_analysis(analysis, csv_path=str(csv_path), output_json_file=output_json_file)
            payload["source_path"] = args.path
            payload["decoder_command"] = args.decoder_command
        elif args.command == "segment-rows":
            fields = [item.strip() for item in args.fields.split(",") if item.strip()] if args.fields else None
            payload = read_segment_rows(args.csv_path, start_row=args.start_row, end_row=args.end_row, fields=fields, pad_rows=args.pad_rows)
        elif args.command in {"filter-evidence", "pid-response", "rpm-filter", "capture-plan", "noise-peaks", "propwash"}:
            analysis = analyze_csv_log(args.csv_path)
            if args.command == "filter-evidence":
                payload = filter_evidence_view(analysis)
            elif args.command == "pid-response":
                payload = pid_response_view(analysis)
            elif args.command == "rpm-filter":
                payload = rpm_filter_view(analysis)
            elif args.command == "capture-plan":
                payload = capture_plan_view(analysis)
            elif args.command == "noise-peaks":
                payload = noise_peak_view(analysis, limit=args.limit)
            else:
                payload = propwash_view(analysis, limit=args.limit)
            payload["csv_path"] = args.csv_path
        else:
            return 2
    except (OSError, RuntimeError, ValueError) as exc:
        payload = _error(exc)
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
