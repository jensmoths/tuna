from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from tuna_core.services.analysis import analyze_imported_log, decode_imported_log, latest_analysis, list_recordings
from tuna_core.services.builds import create_build
from tuna_core.services.diagnoses import record_diagnosis
from tuna_core.services.iterations import complete_no_change, complete_no_change_with_diagnosis, create_iteration
from tuna_core.services.logs import import_blackbox_log
from tuna_core.services.loop_context import get_loop_context
from tuna_core.services.segment_rows import get_segment_rows
from tuna_core.services.loops import create_loop
from tuna_core.services.operator_notifications import create_blackbox_config_notification
from tuna_core.services.operator_tasks import create_build_confirmation_task, create_fcs_connection_task, create_flight_capture_task, create_task, create_tune_goal_task
from tuna_core.services.resume import update_loop_resume_cursor
from tuna_core.services.tune_updates import approve_for_write, mark_applied, propose_tune_update, reject, record_application_failure
from tuna_core.storage import connect, init_db
from tuna_blackbox.analysis_views import compare_analyses, limited_events


def _env_default(name: str, fallback: str) -> str:
    return os.environ.get(name, fallback)


def _row_to_dict(row: Any) -> dict[str, Any]:
    return dict(row) if row is not None else {}


def _print_json(payload: Any) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def _add_json(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")


def _emit(payload: dict[str, Any], json_output: bool) -> None:
    if json_output:
        _print_json(payload)
    else:
        print(next(iter(payload.values())))


def _loads_json_object(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _task_payload(row: Any) -> dict[str, Any]:
    item = _row_to_dict(row)
    item["payload"] = _loads_json_object(item.get("payload_json"))
    item["response"] = _loads_json_object(item.get("response_json")) if item.get("response_json") else None
    return item


def _notification_payload(row: Any) -> dict[str, Any]:
    item = _row_to_dict(row)
    item["payload"] = _loads_json_object(item.get("payload_json"))
    item["acknowledged"] = _loads_json_object(item.get("acknowledged_json")) if item.get("acknowledged_json") else None
    return item


def _metadata_summary(metadata: dict[str, Any]) -> dict[str, Any]:
    fields = metadata.get("fields") if isinstance(metadata.get("fields"), dict) else {}
    return {
        "firmware_type": metadata.get("firmware_type"),
        "firmware_revision": metadata.get("firmware_revision"),
        "firmware_date": metadata.get("firmware_date"),
        "craft_name": metadata.get("craft_name"),
        "data_version": metadata.get("data_version"),
        "pids": metadata.get("pids"),
        "field_counts": {key: len(value) for key, value in fields.items() if isinstance(value, list)},
    }


def _analysis_concise_payload(
    conn: Any,
    *,
    log_id: int,
    payload: dict[str, Any],
    output_json_file: str | None = None,
    csv_path: str | None = None,
) -> dict[str, Any]:
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


def _command_error_payload(exc: BaseException) -> dict[str, Any]:
    return {"error": {"kind": exc.__class__.__name__, "message": str(exc), "retryable": False}}


def _emit_command_error(exc: BaseException, json_output: bool) -> None:
    if json_output:
        _print_json(_command_error_payload(exc))
    else:
        print(str(exc), file=sys.stderr)


def _require_row(row: Any, label: str, row_id: int) -> Any:
    if row is None:
        raise ValueError(f"{label} {row_id} does not exist")
    return row


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
    _require_row(row, "Analysis for Blackbox Log", log_id)
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
        "throttle_chop_analysis": limited_events(analysis.get("throttle_chop_analysis", {}), "segments", 3),
        "cross_axis_flip_analysis": limited_events(analysis.get("cross_axis_flip_analysis", {}), "segments", 3),
        "chirp_analysis": analysis.get("chirp_analysis"),
    }


def _loop_status_payload(conn: Any, loop_id: int) -> dict[str, Any]:
    context = get_loop_context(conn, loop_id, recent_limit=3)
    build = context["build"]
    snapshot = build.get("fc_snapshot") if isinstance(build.get("fc_snapshot"), dict) else {}
    return {
        "loop": context["loop"],
        "build": {
            "id": build["id"],
            "name": build["name"],
            "fc_snapshot_identity": snapshot.get("identity", snapshot),
            "operator_notes": build.get("operator_notes", ""),
        },
        "current_iteration": context["current_iteration"],
        "usable_logs": [
            {
                "id": log["id"],
                "parse_status": log["parse_status"],
                "latest_analysis": log.get("latest_analysis"),
            }
            for log in context["logs"]
            if log.get("parse_status") == "readable"
        ],
        "open_tasks": [{"id": task["id"], "kind": task["kind"], "title": task["title"]} for task in context["open_tasks"]],
        "recent_tasks": [
            {"id": task["id"], "kind": task["kind"], "status": task["status"], "response": task.get("response")}
            for task in context["recent_tasks"]
        ],
        "open_notifications": [{"id": item["id"], "kind": item["kind"], "title": item["title"]} for item in context["open_notifications"]],
        "pending_writes": context["pending_writes"],
        "resume": context["resume"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Tuna Core helper tool for durable Tuna state")
    parser.add_argument("--db", default=_env_default("TUNA_DB", "tuna.sqlite3"), help="SQLite Tuna database path (default: $TUNA_DB or tuna.sqlite3)")
    top = parser.add_subparsers(dest="area", required=True)

    db = top.add_parser("db")
    db_sub = db.add_subparsers(dest="action", required=True)
    _add_json(db_sub.add_parser("init"))

    build = top.add_parser("build")
    build_sub = build.add_subparsers(dest="action", required=True)
    build_create = build_sub.add_parser("create")
    build_create.add_argument("name")
    build_create.add_argument("--fc-snapshot-json", default="{}")
    build_create.add_argument("--operator-notes", default="")
    _add_json(build_create)
    _add_json(build_sub.add_parser("list"))
    build_show = build_sub.add_parser("show")
    build_show.add_argument("--build-id", type=int, required=True)
    _add_json(build_show)

    loop = top.add_parser("loop")
    loop_sub = loop.add_subparsers(dest="action", required=True)
    loop_create = loop_sub.add_parser("create")
    loop_create.add_argument("--build-id", type=int, required=True)
    loop_create.add_argument("--tune-goal", required=True)
    _add_json(loop_create)
    loop_list = loop_sub.add_parser("list")
    loop_list.add_argument("--build-id", type=int)
    _add_json(loop_list)
    loop_context = loop_sub.add_parser("context")
    loop_context.add_argument("--loop-id", type=int, required=True)
    loop_context.add_argument("--recent-limit", type=int, default=5)
    _add_json(loop_context)
    loop_status = loop_sub.add_parser("status")
    loop_status.add_argument("--loop-id", type=int, required=True)
    _add_json(loop_status)

    log = top.add_parser("log")
    log_sub = log.add_subparsers(dest="action", required=True)
    log_import = log_sub.add_parser("import")
    log_import.add_argument("path")
    log_import.add_argument("--build-id", type=int, required=True)
    log_import.add_argument("--loop-id", type=int)
    log_import.add_argument("--storage-dir", default=_env_default("TUNA_LOG_STORAGE_DIR", "tuna-data/blackbox-logs"), help="managed Blackbox Log storage directory (default: $TUNA_LOG_STORAGE_DIR or tuna-data/blackbox-logs)")
    log_import.add_argument("--full-metadata", action="store_true", help="include full parsed Blackbox metadata in JSON output")
    log_import.add_argument("--metadata-json-file", help="write full parsed Blackbox metadata to a file")
    _add_json(log_import)
    log_list = log_sub.add_parser("list")
    log_list.add_argument("--build-id", type=int)
    _add_json(log_list)

    analysis = top.add_parser("analysis")
    analysis_sub = analysis.add_subparsers(dest="action", required=True)
    analysis_decode = analysis_sub.add_parser("decode")
    analysis_decode.add_argument("--log-id", type=int, required=True)
    analysis_decode.add_argument("--output-dir", default=_env_default("TUNA_DECODED_LOG_DIR", "tuna-data/decoded-logs"), help="decoded CSV output directory (default: $TUNA_DECODED_LOG_DIR or tuna-data/decoded-logs)")
    analysis_decode.add_argument("--decoder-command", default=_env_default("TUNA_BLACKBOX_DECODER", "blackbox_decode"), help="Blackbox decoder command (default: $TUNA_BLACKBOX_DECODER or blackbox_decode)")
    _add_json(analysis_decode)
    analysis_analyze = analysis_sub.add_parser("analyze")
    analysis_analyze.add_argument("--log-id", type=int, required=True)
    analysis_analyze.add_argument("--csv-path")
    analysis_analyze.add_argument("--output-json-file", help="write the full analysis JSON to a file and keep CLI JSON concise")
    analysis_analyze.add_argument("--full-json", action="store_true", help="print the full analysis JSON to stdout")
    _add_json(analysis_analyze)
    analysis_decode_analyze = analysis_sub.add_parser("decode-analyze")
    analysis_decode_analyze.add_argument("--log-id", type=int, required=True)
    analysis_decode_analyze.add_argument("--output-dir", default=_env_default("TUNA_DECODED_LOG_DIR", "tuna-data/decoded-logs"), help="decoded CSV output directory (default: $TUNA_DECODED_LOG_DIR or tuna-data/decoded-logs)")
    analysis_decode_analyze.add_argument("--decoder-command", default=_env_default("TUNA_BLACKBOX_DECODER", "blackbox_decode"), help="Blackbox decoder command (default: $TUNA_BLACKBOX_DECODER or blackbox_decode)")
    analysis_decode_analyze.add_argument("--output-json-file", help="write the full analysis JSON to a file and keep CLI JSON concise")
    analysis_decode_analyze.add_argument("--full-json", action="store_true", help="print the full analysis JSON to stdout")
    _add_json(analysis_decode_analyze)
    analysis_summary = analysis_sub.add_parser("summary")
    analysis_summary.add_argument("--log-id", type=int, required=True)
    _add_json(analysis_summary)
    analysis_segment_rows = analysis_sub.add_parser("segment-rows")
    analysis_segment_rows.add_argument("--log-id", type=int, required=True)
    analysis_segment_rows.add_argument("--segment-kind", required=True, choices=["high_rate", "throttle_punch", "chirp"])
    analysis_segment_rows.add_argument("--segment-index", type=int, required=True)
    analysis_segment_rows.add_argument("--fields", help="comma-separated decoded CSV fields to return")
    analysis_segment_rows.add_argument("--pad-rows", type=int, default=0)
    analysis_segment_rows.add_argument("--max-rows", type=int, default=500)
    _add_json(analysis_segment_rows)
    analysis_recordings = analysis_sub.add_parser("recordings", aliases=["list-recordings"])
    analysis_recordings.add_argument("--log-id", type=int, required=True)
    analysis_recordings.add_argument("--sort", choices=["decoded", "start-time", "activity"], default="decoded")
    analysis_recordings.add_argument("--limit", type=int)
    _add_json(analysis_recordings)
    analysis_compare = analysis_sub.add_parser("compare")
    analysis_compare.add_argument("--before-log-id", type=int, required=True)
    analysis_compare.add_argument("--after-log-id", type=int, required=True)
    _add_json(analysis_compare)
    analysis_throttle_chop = analysis_sub.add_parser("throttle-chop")
    analysis_throttle_chop.add_argument("--log-id", type=int, required=True)
    analysis_throttle_chop.add_argument("--limit", type=int, default=5)
    _add_json(analysis_throttle_chop)
    analysis_cross_axis_flip = analysis_sub.add_parser("cross-axis-flip")
    analysis_cross_axis_flip.add_argument("--log-id", type=int, required=True)
    analysis_cross_axis_flip.add_argument("--limit", type=int, default=5)
    _add_json(analysis_cross_axis_flip)

    iteration = top.add_parser("iteration")
    iteration_sub = iteration.add_subparsers(dest="action", required=True)
    iteration_create = iteration_sub.add_parser("create")
    iteration_create.add_argument("--loop-id", type=int, required=True)
    iteration_create.add_argument("--log-id", type=int, action="append", default=[])
    _add_json(iteration_create)
    iteration_current = iteration_sub.add_parser("current")
    iteration_current.add_argument("--loop-id", type=int, required=True)
    _add_json(iteration_current)
    iteration_no_change = iteration_sub.add_parser("complete-no-change")
    iteration_no_change.add_argument("--iteration-id", type=int, required=True)
    iteration_no_change.add_argument("--reason", required=True)
    _add_json(iteration_no_change)
    iteration_complete_with_diagnosis = iteration_sub.add_parser("complete-with-diagnosis")
    iteration_complete_with_diagnosis.add_argument("--iteration-id", type=int, required=True)
    iteration_complete_with_diagnosis.add_argument("--body", required=True)
    iteration_complete_with_diagnosis.add_argument("--reason", required=True)
    iteration_complete_with_diagnosis.add_argument("--confidence", default="")
    iteration_complete_with_diagnosis.add_argument("--evidence-json", default="{}")
    iteration_complete_with_diagnosis.add_argument("--result", choices=("no_change",), default="no_change")
    _add_json(iteration_complete_with_diagnosis)

    diagnosis = top.add_parser("diagnosis")
    diagnosis_sub = diagnosis.add_subparsers(dest="action", required=True)
    diagnosis_record = diagnosis_sub.add_parser("record")
    diagnosis_record.add_argument("--iteration-id", type=int, required=True)
    diagnosis_record.add_argument("--body", required=True)
    diagnosis_record.add_argument("--confidence", default="")
    diagnosis_record.add_argument("--evidence-json", default="{}")
    _add_json(diagnosis_record)

    update = top.add_parser("update")
    update_sub = update.add_subparsers(dest="action", required=True)
    update_pending = update_sub.add_parser("pending-writes")
    _add_json(update_pending)
    update_propose = update_sub.add_parser("propose")
    update_propose.add_argument("--iteration-id", type=int, required=True)
    update_propose.add_argument("--build-id", type=int, required=True)
    update_propose.add_argument("--settings-json", required=True)
    update_propose.add_argument("--cli-text", default="")
    _add_json(update_propose)
    update_approve = update_sub.add_parser("approve-for-write")
    update_approve.add_argument("--update-id", type=int, required=True)
    _add_json(update_approve)
    update_fail = update_sub.add_parser("record-write-failure")
    update_fail.add_argument("--update-id", type=int, required=True)
    update_fail.add_argument("--failure", required=True)
    _add_json(update_fail)
    update_apply = update_sub.add_parser("apply")
    update_apply.add_argument("--update-id", type=int, required=True)
    _add_json(update_apply)
    update_reject = update_sub.add_parser("reject")
    update_reject.add_argument("--update-id", type=int, required=True)
    update_reject.add_argument("--reason", required=True)
    _add_json(update_reject)

    task = top.add_parser("task")
    task_sub = task.add_subparsers(dest="action", required=True)
    task_create = task_sub.add_parser("create")
    task_create.add_argument("--kind", required=True)
    task_create.add_argument("--title", required=True)
    task_create.add_argument("--body", default="")
    task_create.add_argument("--payload-json", default="{}")
    _add_json(task_create)
    task_flight = task_sub.add_parser("request-flight-capture")
    task_flight.add_argument("--build-id", type=int)
    task_flight.add_argument("--loop-id", type=int)
    task_flight.add_argument("--reason", default="Need another Blackbox Log for tuning evidence.")
    task_flight.add_argument("--capture-goal", default="Capture a useful follow-up Blackbox Log for the current Tune Goal.")
    _add_json(task_flight)
    task_fcs = task_sub.add_parser("request-fcs-connection")
    task_fcs.add_argument("--build-id", type=int)
    task_fcs.add_argument("--loop-id", type=int)
    task_fcs.add_argument("--bridge-host", default=_env_default("FCS_BRIDGE_HOST", "tuna-bridge-usb"), help="FCS Bridge host to ask the Operator to restore (default: $FCS_BRIDGE_HOST or tuna-bridge-usb)")
    task_fcs.add_argument("--reason", default="FCS Bridge connection is required before the Tuning Agent can continue.")
    task_fcs.add_argument("--next-step", default="Restore the FC/Bridge connection in USB CDC/MSP mode.")
    _add_json(task_fcs)
    task_build = task_sub.add_parser("confirm-build")
    task_build.add_argument("--fc-snapshot-json", required=True)
    task_build.add_argument("--candidate-build-id", type=int)
    task_build.add_argument("--reason", default="")
    _add_json(task_build)
    task_goal = task_sub.add_parser("request-tune-goal")
    task_goal.add_argument("--build-id", type=int)
    task_goal.add_argument("--reason", default="Define the Tune Goal before starting a Loop.")
    _add_json(task_goal)
    task_list = task_sub.add_parser("list")
    task_list.add_argument("--status", choices=("open", "resolved", "all"), default="all")
    task_list.add_argument("--limit", type=int)
    _add_json(task_list)
    task_show = task_sub.add_parser("show")
    task_show.add_argument("--task-id", type=int, required=True)
    _add_json(task_show)

    notify = top.add_parser("notification", aliases=["notify"])
    notify_sub = notify.add_subparsers(dest="action", required=True)
    notify_blackbox = notify_sub.add_parser("blackbox-config-changed")
    notify_blackbox.add_argument("--build-id", type=int)
    notify_blackbox.add_argument("--loop-id", type=int)
    notify_blackbox.add_argument("--settings-json", required=True)
    notify_blackbox.add_argument("--previous-settings-json", default="{}")
    notify_blackbox.add_argument("--reason", required=True)
    notify_blackbox.add_argument("--impact", default="")
    _add_json(notify_blackbox)
    notify_list = notify_sub.add_parser("list")
    notify_list.add_argument("--status", choices=("open", "acknowledged", "all"), default="all")
    notify_list.add_argument("--limit", type=int)
    _add_json(notify_list)

    status = top.add_parser("status")
    _add_json(status)

    args = parser.parse_args(argv)
    conn = connect(args.db)

    if args.area == "db" and args.action == "init":
        init_db(conn)
        _emit({"db": args.db}, args.json)
        return 0

    init_db(conn)

    if args.area == "build" and args.action == "create":
        build_id = create_build(conn, args.name, fc_snapshot=json.loads(args.fc_snapshot_json), operator_notes=args.operator_notes)
        _emit({"build_id": build_id}, args.json)
    elif args.area == "build" and args.action == "list":
        _print_json([_row_to_dict(row) for row in conn.execute("SELECT * FROM builds ORDER BY id")])
    elif args.area == "build" and args.action == "show":
        try:
            row = _require_row(conn.execute("SELECT * FROM builds WHERE id = ?", (args.build_id,)).fetchone(), "Build", args.build_id)
        except ValueError as exc:
            _emit_command_error(exc, args.json)
            return 1
        payload = _row_to_dict(row)
        payload["fc_snapshot"] = json.loads(payload.pop("fc_snapshot_json"))
        _print_json(payload)
    elif args.area == "loop" and args.action == "create":
        loop_id = create_loop(conn, args.build_id, args.tune_goal)
        _emit({"loop_id": loop_id}, args.json)
    elif args.area == "loop" and args.action == "list":
        sql = "SELECT * FROM loops"
        params: tuple[Any, ...] = ()
        if args.build_id is not None:
            sql += " WHERE build_id = ?"
            params = (args.build_id,)
        _print_json([_row_to_dict(row) for row in conn.execute(sql + " ORDER BY id", params)])
    elif args.area == "loop" and args.action == "context":
        try:
            payload = get_loop_context(conn, args.loop_id, recent_limit=args.recent_limit)
        except ValueError as exc:
            if args.json:
                _print_json({"error": {"kind": exc.__class__.__name__, "message": str(exc)}})
            else:
                print(str(exc), file=sys.stderr)
            return 1
        _print_json(payload)
    elif args.area == "loop" and args.action == "status":
        try:
            payload = _loop_status_payload(conn, args.loop_id)
        except ValueError as exc:
            _emit_command_error(exc, args.json)
            return 1
        _print_json(payload)
    elif args.area == "log" and args.action == "import":
        log_id = import_blackbox_log(conn, Path(args.path), build_id=args.build_id, storage_dir=args.storage_dir)
        row = conn.execute(
            """
            SELECT id AS log_id, build_id, managed_path, sha256, size_bytes, parse_status, imported_at, metadata_json, warnings_json
            FROM blackbox_logs
            WHERE id = ?
            """,
            (log_id,),
        ).fetchone()
        payload = _row_to_dict(row)
        metadata = json.loads(payload.pop("metadata_json"))
        payload["warnings"] = json.loads(payload.pop("warnings_json"))
        payload["metadata_summary"] = _metadata_summary(metadata)
        if args.metadata_json_file:
            metadata_path = Path(args.metadata_json_file)
            metadata_path.parent.mkdir(parents=True, exist_ok=True)
            metadata_path.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n")
            payload["metadata_json_file"] = str(metadata_path)
        if args.full_metadata:
            payload["metadata"] = metadata
        update_loop_resume_cursor(
            conn,
            args.loop_id,
            last_import={"log_id": log_id, "path": payload["managed_path"], "parse_status": payload["parse_status"]},
        )
        _emit(payload, args.json)
    elif args.area == "analysis" and args.action == "decode":
        try:
            payload = decode_imported_log(conn, args.log_id, output_dir=args.output_dir, decoder_command=args.decoder_command)
        except (OSError, RuntimeError, ValueError) as exc:
            _emit_command_error(exc, args.json)
            return 1
        _emit(payload, args.json)
    elif args.area == "analysis" and args.action == "analyze":
        try:
            payload = analyze_imported_log(conn, args.log_id, csv_path=args.csv_path)
        except (OSError, RuntimeError, ValueError) as exc:
            _emit_command_error(exc, args.json)
            return 1
        output_json_file = _write_analysis_file(args.output_json_file, payload)
        concise_payload = _analysis_concise_payload(conn, log_id=args.log_id, payload=payload, output_json_file=output_json_file)
        if args.json:
            _print_json(payload if args.full_json else concise_payload)
        else:
            if output_json_file:
                print(output_json_file)
            else:
                print(payload["duration_seconds"])
    elif args.area == "analysis" and args.action == "decode-analyze":
        try:
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
        except (OSError, RuntimeError, ValueError) as exc:
            _emit_command_error(exc, args.json)
            return 1
        output_json_file = _write_analysis_file(args.output_json_file, payload)
        concise_payload = _analysis_concise_payload(
            conn,
            log_id=args.log_id,
            payload=payload,
            output_json_file=output_json_file,
            csv_path=str(decoded["csv_path"]),
        )
        concise_payload["recordings"] = recording_summaries
        if args.json:
            _print_json(payload if args.full_json else concise_payload)
        else:
            print(decoded["csv_path"])
    elif args.area == "analysis" and args.action == "segment-rows":
        fields = [field.strip() for field in args.fields.split(",")] if args.fields else None
        try:
            payload = get_segment_rows(
                conn,
                log_id=args.log_id,
                segment_kind=args.segment_kind,
                segment_index=args.segment_index,
                fields=fields,
                pad_rows=args.pad_rows,
                max_rows=args.max_rows,
            )
        except (OSError, RuntimeError, ValueError) as exc:
            _emit_command_error(exc, args.json)
            return 1
        if args.json:
            _print_json(payload)
        else:
            print(len(payload["rows"]))
    elif args.area == "analysis" and args.action in {"recordings", "list-recordings"}:
        try:
            payload = list_recordings(conn, args.log_id, sort=args.sort, limit=args.limit)
        except (json.JSONDecodeError, ValueError) as exc:
            _emit_command_error(exc, args.json)
            return 1
        _print_json(payload)
    elif args.area == "analysis" and args.action == "compare":
        try:
            before_id, before_at, before = latest_analysis(conn, args.before_log_id)
            after_id, after_at, after = latest_analysis(conn, args.after_log_id)
            payload = compare_analyses(before, after)
            payload["before"].update({"log_id": args.before_log_id, "analysis_id": before_id, "analyzed_at": before_at})
            payload["after"].update({"log_id": args.after_log_id, "analysis_id": after_id, "analyzed_at": after_at})
        except (json.JSONDecodeError, ValueError) as exc:
            _emit_command_error(exc, args.json)
            return 1
        _print_json(payload)
    elif args.area == "analysis" and args.action == "throttle-chop":
        try:
            analysis_id, analyzed_at, analysis = latest_analysis(conn, args.log_id)
            payload = limited_events(analysis.get("throttle_chop_analysis", {"available": False, "warnings": ["Analysis does not include throttle-chop data"]}), "segments", args.limit)
            payload.update({"log_id": args.log_id, "analysis_id": analysis_id, "analyzed_at": analyzed_at})
        except (json.JSONDecodeError, ValueError) as exc:
            _emit_command_error(exc, args.json)
            return 1
        _print_json(payload)
    elif args.area == "analysis" and args.action == "cross-axis-flip":
        try:
            analysis_id, analyzed_at, analysis = latest_analysis(conn, args.log_id)
            payload = limited_events(analysis.get("cross_axis_flip_analysis", {"available": False, "warnings": ["Analysis does not include cross-axis flip data"]}), "segments", args.limit)
            payload.update({"log_id": args.log_id, "analysis_id": analysis_id, "analyzed_at": analyzed_at})
        except (json.JSONDecodeError, ValueError) as exc:
            _emit_command_error(exc, args.json)
            return 1
        _print_json(payload)
    elif args.area == "analysis" and args.action == "summary":
        try:
            payload = _analysis_summary_payload(conn, args.log_id)
        except (json.JSONDecodeError, ValueError) as exc:
            _emit_command_error(exc, args.json)
            return 1
        _print_json(payload)
    elif args.area == "log" and args.action == "list":
        sql = "SELECT id, build_id, managed_path, sha256, size_bytes, parse_status, imported_at FROM blackbox_logs"
        params = ()
        if args.build_id is not None:
            sql += " WHERE build_id = ?"
            params = (args.build_id,)
        _print_json([_row_to_dict(row) for row in conn.execute(sql + " ORDER BY id", params)])
    elif args.area == "iteration" and args.action == "create":
        iteration_id = create_iteration(conn, args.loop_id, args.log_id)
        _emit({"iteration_id": iteration_id}, args.json)
    elif args.area == "iteration" and args.action == "current":
        row = conn.execute("SELECT * FROM tuning_iterations WHERE loop_id = ? AND status = 'open'", (args.loop_id,)).fetchone()
        _print_json(_row_to_dict(row))
    elif args.area == "iteration" and args.action == "complete-no-change":
        try:
            complete_no_change(conn, args.iteration_id, args.reason)
        except ValueError as exc:
            _emit_command_error(exc, args.json)
            return 1
        row = conn.execute("SELECT * FROM tuning_iterations WHERE id = ?", (args.iteration_id,)).fetchone()
        _print_json(_row_to_dict(row) if args.json else {"iteration_id": args.iteration_id})
    elif args.area == "iteration" and args.action == "complete-with-diagnosis":
        try:
            diagnosis_id = complete_no_change_with_diagnosis(
                conn,
                args.iteration_id,
                body=args.body,
                reason=args.reason,
                confidence=args.confidence,
                evidence=json.loads(args.evidence_json),
            )
        except (json.JSONDecodeError, ValueError) as exc:
            _emit_command_error(exc, args.json)
            return 1
        row = conn.execute("SELECT * FROM tuning_iterations WHERE id = ?", (args.iteration_id,)).fetchone()
        payload = _row_to_dict(row)
        payload["diagnosis_id"] = diagnosis_id
        _print_json(payload)
    elif args.area == "diagnosis" and args.action == "record":
        try:
            diagnosis_id = record_diagnosis(conn, args.iteration_id, args.body, confidence=args.confidence, evidence=json.loads(args.evidence_json))
        except (json.JSONDecodeError, ValueError) as exc:
            _emit_command_error(exc, args.json)
            return 1
        _emit({"diagnosis_id": diagnosis_id}, args.json)
    elif args.area == "update" and args.action == "pending-writes":
        rows = conn.execute(
            """
            SELECT
              u.id AS update_id,
              u.iteration_id,
              u.build_id,
              u.settings_json,
              u.cli_text,
              u.application_failure,
              d.body AS diagnosis,
              d.confidence AS diagnosis_confidence
            FROM tune_updates u
            LEFT JOIN diagnoses d ON d.iteration_id = u.iteration_id
            WHERE u.status IN ('approved_pending_write', 'write_failed')
            ORDER BY u.decided_at, u.id
            """
        ).fetchall()
        payload = []
        for row in rows:
            item = _row_to_dict(row)
            item["settings"] = json.loads(item.pop("settings_json"))
            payload.append(item)
        _print_json(payload)
    elif args.area == "update" and args.action == "propose":
        update_id = propose_tune_update(conn, args.iteration_id, args.build_id, json.loads(args.settings_json), cli_text=args.cli_text)
        _emit({"update_id": update_id}, args.json)
    elif args.area == "update" and args.action == "approve-for-write":
        approve_for_write(conn, args.update_id)
        _emit({"update_id": args.update_id, "status": "approved_pending_write"}, args.json)
    elif args.area == "update" and args.action == "record-write-failure":
        record_application_failure(conn, args.update_id, args.failure)
        _emit({"update_id": args.update_id, "status": "write_failed"}, args.json)
    elif args.area == "update" and args.action == "apply":
        mark_applied(conn, args.update_id)
        _emit({"update_id": args.update_id, "status": "applied"}, args.json)
    elif args.area == "update" and args.action == "reject":
        reject(conn, args.update_id, args.reason)
        _emit({"update_id": args.update_id, "status": "rejected"}, args.json)
    elif args.area == "task" and args.action == "create":
        task_id = create_task(conn, args.kind, args.title, body=args.body, payload=json.loads(args.payload_json))
        _emit({"task_id": task_id}, args.json)
    elif args.area == "task" and args.action == "request-flight-capture":
        task_id = create_flight_capture_task(conn, build_id=args.build_id, loop_id=args.loop_id, reason=args.reason, capture_goal=args.capture_goal)
        _emit({"task_id": task_id, "kind": "request_flight_capture"}, args.json)
    elif args.area == "task" and args.action == "request-fcs-connection":
        task_id = create_fcs_connection_task(
            conn,
            build_id=args.build_id,
            loop_id=args.loop_id,
            bridge_host=args.bridge_host,
            reason=args.reason,
            next_step=args.next_step,
        )
        _emit({"task_id": task_id, "kind": "request_fcs_connection"}, args.json)
    elif args.area == "task" and args.action == "confirm-build":
        task_id = create_build_confirmation_task(
            conn,
            fc_snapshot=json.loads(args.fc_snapshot_json),
            candidate_build_id=args.candidate_build_id,
            reason=args.reason,
        )
        _emit({"task_id": task_id, "kind": "confirm_build"}, args.json)
    elif args.area == "task" and args.action == "request-tune-goal":
        task_id = create_tune_goal_task(conn, build_id=args.build_id, reason=args.reason)
        _emit({"task_id": task_id, "kind": "request_tune_goal"}, args.json)
    elif args.area == "task" and args.action == "list":
        sql = "SELECT * FROM operator_tasks"
        params: list[Any] = []
        if args.status != "all":
            sql += " WHERE status = ?"
            params.append(args.status)
        sql += " ORDER BY status, created_at DESC, id DESC"
        if args.limit is not None:
            sql += " LIMIT ?"
            params.append(args.limit)
        _print_json([_task_payload(row) for row in conn.execute(sql, tuple(params))])
    elif args.area == "task" and args.action == "show":
        try:
            row = _require_row(conn.execute("SELECT * FROM operator_tasks WHERE id = ?", (args.task_id,)).fetchone(), "Operator Task", args.task_id)
        except ValueError as exc:
            _emit_command_error(exc, args.json)
            return 1
        _print_json(_task_payload(row))
    elif args.area in ("notify", "notification") and args.action == "blackbox-config-changed":
        notification_id = create_blackbox_config_notification(
            conn,
            build_id=args.build_id,
            loop_id=args.loop_id,
            settings=json.loads(args.settings_json),
            previous_settings=json.loads(args.previous_settings_json),
            reason=args.reason,
            impact=args.impact,
        )
        _emit({"notification_id": notification_id, "kind": "blackbox_config_changed"}, args.json)
    elif args.area in ("notify", "notification") and args.action == "list":
        sql = "SELECT * FROM operator_notifications"
        params: list[Any] = []
        if args.status != "all":
            sql += " WHERE status = ?"
            params.append(args.status)
        sql += " ORDER BY status, created_at DESC, id DESC"
        if args.limit is not None:
            sql += " LIMIT ?"
            params.append(args.limit)
        _print_json([_notification_payload(row) for row in conn.execute(sql, tuple(params))])
    elif args.area == "status":
        _print_json({
            "builds": conn.execute("SELECT COUNT(*) FROM builds").fetchone()[0],
            "loops_open": conn.execute("SELECT COUNT(*) FROM loops WHERE status = 'open'").fetchone()[0],
            "iterations_open": conn.execute("SELECT COUNT(*) FROM tuning_iterations WHERE status = 'open'").fetchone()[0],
            "logs": conn.execute("SELECT COUNT(*) FROM blackbox_logs").fetchone()[0],
            "open_tasks": conn.execute("SELECT COUNT(*) FROM operator_tasks WHERE status = 'open'").fetchone()[0],
            "open_notifications": conn.execute("SELECT COUNT(*) FROM operator_notifications WHERE status = 'open'").fetchone()[0],
            "pending_writes": conn.execute("SELECT COUNT(*) FROM tune_updates WHERE status = 'approved_pending_write'").fetchone()[0],
        })
    else:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
