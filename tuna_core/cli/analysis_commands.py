from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tuna_blackbox.analysis_views import capture_plan_view, compare_analyses, filter_evidence_view, limited_events, noise_peak_view, pid_response_view, propwash_view, rpm_filter_view
from tuna_core.cli.output import emit, emit_command_error, print_json, require_row
from tuna_core.services.analysis import analyze_imported_log, analysis_fixture_scenario, decode_imported_log, latest_analysis, list_recordings, record_analysis_fixture
from tuna_core.services.segment_rows import get_segment_rows


def _loads_json_object(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _analysis_concise_payload(conn: Any, *, log_id: int, payload: dict[str, Any], output_json_file: str | None = None, csv_path: str | None = None) -> dict[str, Any]:
    analysis_row = conn.execute(
        "SELECT id, analyzed_at FROM log_analyses WHERE log_id = ? ORDER BY analyzed_at DESC, id DESC LIMIT 1",
        (log_id,),
    ).fetchone()
    concise_payload = {
        "log_id": log_id,
        "analysis_id": analysis_row["id"] if analysis_row else None,
        "analyzed_at": analysis_row["analyzed_at"] if analysis_row else None,
        "row_count": payload.get("row_count"),
        "duration_seconds": payload.get("duration_seconds"),
        "quality": payload.get("quality"),
        "warnings": payload.get("warnings", []),
        "analysis_json_file": output_json_file,
        "full_analysis_stored": True,
    }
    if csv_path is not None:
        concise_payload["csv_path"] = csv_path
    return concise_payload


def _write_analysis_file(path_text: str | None, payload: dict[str, Any]) -> str | None:
    if not path_text:
        return None
    output_path = Path(path_text)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return str(output_path)


def _read_analysis_fixture(path_text: str) -> dict[str, Any]:
    path = Path(path_text)
    try:
        payload = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ValueError(f"Analysis fixture must be valid JSON: {exc.msg}") from exc
    if not isinstance(payload, dict):
        raise ValueError("Analysis fixture must be a JSON object")
    return payload


def _compact_segment(segment: dict[str, Any]) -> dict[str, Any]:
    compact = {key: value for key, value in segment.items() if key != "raw_data_ref"}
    ref = segment.get("raw_data_ref")
    if isinstance(ref, dict):
        compact["raw_data_ref"] = {key: ref.get(key) for key in ("start_row", "end_row", "start_time_us", "end_time_us") if key in ref}
    return compact


def _summary_config_snapshot(conn: Any, log_id: int, analysis: dict[str, Any]) -> dict[str, Any] | None:
    snapshot = analysis.get("config_snapshot") if isinstance(analysis.get("config_snapshot"), dict) else None
    if snapshot and snapshot.get("available"):
        return snapshot
    row = conn.execute("SELECT metadata_json FROM blackbox_logs WHERE id = ?", (log_id,)).fetchone()
    if row is None:
        return snapshot
    metadata = _loads_json_object(row["metadata_json"])
    pids = metadata.get("pids") if isinstance(metadata.get("pids"), dict) else {}
    if pids:
        return {"available": True, "pids": pids, "settings": {}}
    return snapshot


def _analysis_summary_payload(conn: Any, log_id: int) -> dict[str, Any]:
    row = conn.execute(
        "SELECT id, analyzed_at, analysis_json FROM log_analyses WHERE log_id = ? ORDER BY analyzed_at DESC, id DESC LIMIT 1",
        (log_id,),
    ).fetchone()
    require_row(row, "Analysis for Blackbox Log", log_id)
    analysis = json.loads(row["analysis_json"])
    segments = analysis.get("segments") if isinstance(analysis.get("segments"), dict) else {}
    segment_counts = {kind: len(items) for kind, items in segments.items() if isinstance(items, list)}
    segment_examples = {
        kind: [_compact_segment(segment) for segment in items[:3] if isinstance(segment, dict)]
        for kind, items in segments.items()
        if isinstance(items, list) and items
    }
    return {
        "log_id": log_id,
        "analysis_id": row["id"],
        "analyzed_at": row["analyzed_at"],
        "row_count": analysis.get("row_count"),
        "duration_seconds": analysis.get("duration_seconds"),
        "quality": analysis.get("quality"),
        "warnings": analysis.get("warnings", []),
        "activity": analysis.get("activity"),
        "flight": analysis.get("flight"),
        "config_snapshot": _summary_config_snapshot(conn, log_id, analysis),
        "segment_counts": segment_counts,
        "segment_examples": segment_examples,
        "pid_term_analysis": analysis.get("pid_term_analysis"),
        "motor_analysis": analysis.get("motor_analysis"),
        "filter_diagnosis": (analysis.get("tuning_evidence") or {}).get("filter_diagnosis") if isinstance(analysis.get("tuning_evidence"), dict) else None,
        "pid_response": (analysis.get("tuning_evidence") or {}).get("pid_response") if isinstance(analysis.get("tuning_evidence"), dict) else None,
        "capture_plan": (analysis.get("tuning_evidence") or {}).get("capture_plan") if isinstance(analysis.get("tuning_evidence"), dict) else None,
        "throttle_chop_analysis": limited_events(analysis.get("throttle_chop_analysis", {}), "segments", 3),
        "cross_axis_flip_analysis": limited_events(analysis.get("cross_axis_flip_analysis", {}), "segments", 3),
        "propwash_analysis": limited_events(analysis.get("propwash_analysis", {}), "segments", 3),
        "chirp_analysis": analysis.get("chirp_analysis"),
    }


def _decode_analyze(conn: Any, args: Any) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    decoded = decode_imported_log(conn, args.log_id, output_dir=args.output_dir, decoder_command=args.decoder_command)
    decoded_recordings = decoded.get("recordings") if isinstance(decoded.get("recordings"), list) else []
    csv_paths = [item.get("csv_path") for item in decoded_recordings if isinstance(item, dict) and item.get("csv_path")]
    if not csv_paths:
        csv_paths = [decoded["csv_path"]]
    payload = None
    recording_summaries = []
    for csv_path in dict.fromkeys(str(path) for path in csv_paths):
        analysis_payload = analyze_imported_log(conn, args.log_id, csv_path=csv_path)
        recording_summaries.append({"csv_path": csv_path, "row_count": analysis_payload.get("row_count"), "duration_seconds": analysis_payload.get("duration_seconds"), "quality": analysis_payload.get("quality")})
        if csv_path == str(decoded["csv_path"]):
            payload = analysis_payload
    if payload is None:
        payload = analyze_imported_log(conn, args.log_id, csv_path=decoded["csv_path"])
    return decoded, payload, recording_summaries


def handle_analysis_command(conn: Any, args: Any) -> int | None:
    if args.area != "analysis":
        return None
    for handler in (_handle_decode_commands, _handle_view_commands, _handle_event_commands):
        handled = handler(conn, args)
        if handled is not None:
            return handled
    return None


def _handle_decode_commands(conn: Any, args: Any) -> int | None:
    if args.action == "decode":
        try:
            payload = decode_imported_log(conn, args.log_id, output_dir=args.output_dir, decoder_command=args.decoder_command)
        except (OSError, RuntimeError, ValueError) as exc:
            emit_command_error(exc, args.json)
            return 1
        emit(payload, args.json)
    elif args.action == "analyze":
        try:
            payload = analyze_imported_log(conn, args.log_id, csv_path=args.csv_path)
        except (OSError, RuntimeError, ValueError) as exc:
            emit_command_error(exc, args.json)
            return 1
        output_json_file = _write_analysis_file(args.output_json_file, payload)
        concise_payload = _analysis_concise_payload(conn, log_id=args.log_id, payload=payload, output_json_file=output_json_file)
        print_json(payload if args.full_json else concise_payload) if args.json else print(output_json_file or payload["duration_seconds"])
    elif args.action == "decode-analyze":
        try:
            decoded, payload, recording_summaries = _decode_analyze(conn, args)
        except (OSError, RuntimeError, ValueError) as exc:
            emit_command_error(exc, args.json)
            return 1
        output_json_file = _write_analysis_file(args.output_json_file, payload)
        concise_payload = _analysis_concise_payload(conn, log_id=args.log_id, payload=payload, output_json_file=output_json_file, csv_path=str(decoded["csv_path"]))
        concise_payload["recordings"] = recording_summaries
        print_json(payload if args.full_json else concise_payload) if args.json else print(decoded["csv_path"])
    elif args.action == "record-fixture":
        try:
            fixture_payload = analysis_fixture_scenario(args.scenario) if args.scenario else _read_analysis_fixture(args.analysis_json_file)
            payload = record_analysis_fixture(conn, args.log_id, fixture_payload)
        except (OSError, RuntimeError, ValueError) as exc:
            emit_command_error(exc, args.json)
            return 1
        concise_payload = _analysis_concise_payload(conn, log_id=args.log_id, payload=payload, output_json_file=args.analysis_json_file)
        if args.scenario:
            concise_payload["scenario"] = args.scenario
        print_json(payload if args.full_json else concise_payload) if args.json else print(args.scenario or args.analysis_json_file)
    else:
        return None
    return 0


def _handle_view_commands(conn: Any, args: Any) -> int | None:
    if args.action == "segment-rows":
        fields = [field.strip() for field in args.fields.split(",")] if args.fields else None
        try:
            payload = get_segment_rows(conn, log_id=args.log_id, segment_kind=args.segment_kind, segment_index=args.segment_index, fields=fields, pad_rows=args.pad_rows, max_rows=args.max_rows)
        except (OSError, RuntimeError, ValueError) as exc:
            emit_command_error(exc, args.json)
            return 1
        print_json(payload) if args.json else print(len(payload["rows"]))
    elif args.action in {"recordings", "list-recordings"}:
        try:
            payload = list_recordings(conn, args.log_id, sort=args.sort, limit=args.limit)
        except (json.JSONDecodeError, ValueError) as exc:
            emit_command_error(exc, args.json)
            return 1
        print_json(payload)
    elif args.action == "compare":
        try:
            before_id, before_at, before = latest_analysis(conn, args.before_log_id)
            after_id, after_at, after = latest_analysis(conn, args.after_log_id)
            payload = compare_analyses(before, after)
            payload["before"].update({"log_id": args.before_log_id, "analysis_id": before_id, "analyzed_at": before_at})
            payload["after"].update({"log_id": args.after_log_id, "analysis_id": after_id, "analyzed_at": after_at})
        except (json.JSONDecodeError, ValueError) as exc:
            emit_command_error(exc, args.json)
            return 1
        print_json(payload)
    elif args.action == "summary":
        try:
            payload = _analysis_summary_payload(conn, args.log_id)
        except (json.JSONDecodeError, ValueError) as exc:
            emit_command_error(exc, args.json)
            return 1
        print_json(payload)
    else:
        return None
    return 0


def _handle_event_commands(conn: Any, args: Any) -> int | None:
    if args.action in {"throttle-chop", "cross-axis-flip", "noise-peaks", "propwash"}:
        key_by_action = {
            "throttle-chop": "throttle_chop_analysis",
            "cross-axis-flip": "cross_axis_flip_analysis",
        }
        key = key_by_action.get(args.action)
        warning = f"Analysis does not include {args.action} data"
        try:
            analysis_id, analyzed_at, analysis = latest_analysis(conn, args.log_id)
            if args.action == "noise-peaks":
                payload = noise_peak_view(analysis, limit=args.limit)
            elif args.action == "propwash":
                payload = propwash_view(analysis, limit=args.limit)
            else:
                payload = limited_events(analysis.get(key, {"available": False, "warnings": [warning]}), "segments", args.limit)
            payload.update({"log_id": args.log_id, "analysis_id": analysis_id, "analyzed_at": analyzed_at})
        except (json.JSONDecodeError, ValueError) as exc:
            emit_command_error(exc, args.json)
            return 1
        print_json(payload)
    elif args.action in {"filter-evidence", "pid-response", "rpm-filter", "capture-plan"}:
        try:
            analysis_id, analyzed_at, analysis = latest_analysis(conn, args.log_id)
            if args.action == "filter-evidence":
                payload = filter_evidence_view(analysis)
            elif args.action == "pid-response":
                payload = pid_response_view(analysis)
            elif args.action == "rpm-filter":
                payload = rpm_filter_view(analysis)
            else:
                payload = capture_plan_view(analysis)
            payload.update({"log_id": args.log_id, "analysis_id": analysis_id, "analyzed_at": analyzed_at})
        except (json.JSONDecodeError, ValueError) as exc:
            emit_command_error(exc, args.json)
            return 1
        print_json(payload)
    else:
        return None
    return 0
