from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from tune.services.analysis import analyze_imported_log, decode_imported_log
from tune.services.builds import create_build
from tune.services.diagnoses import record_diagnosis
from tune.services.fcs_transfer import transfer_blackbox_log_from_bridge
from tune.services.iterations import create_iteration
from tune.services.logs import import_blackbox_log
from tune.services.segment_rows import get_segment_rows
from tune.services.loops import create_loop
from tune.services.operator_tasks import create_task
from tune.services.tune_updates import approve_for_write, mark_applied, propose_tune_update, reject, record_application_failure
from tune.storage import connect, init_db


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Tune helper tool for Tuna state")
    parser.add_argument("--db", default="tune.sqlite3")
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

    loop = top.add_parser("loop")
    loop_sub = loop.add_subparsers(dest="action", required=True)
    loop_create = loop_sub.add_parser("create")
    loop_create.add_argument("--build-id", type=int, required=True)
    loop_create.add_argument("--tune-goal", required=True)
    _add_json(loop_create)
    loop_list = loop_sub.add_parser("list")
    loop_list.add_argument("--build-id", type=int)
    _add_json(loop_list)

    log = top.add_parser("log")
    log_sub = log.add_subparsers(dest="action", required=True)
    log_import = log_sub.add_parser("import")
    log_import.add_argument("path")
    log_import.add_argument("--build-id", type=int, required=True)
    log_import.add_argument("--storage-dir", default="tune-data/blackbox-logs")
    _add_json(log_import)
    log_transfer = log_sub.add_parser("transfer")
    log_transfer.add_argument("--bridge-host", default="tuna-bridge-usb")
    log_transfer.add_argument("--output", required=True)
    log_transfer.add_argument("--size", type=int, required=True)
    log_transfer.add_argument("--timeout", type=float, default=60.0)
    log_transfer.add_argument("--chunk-size", type=int, default=1024 * 1024, help="raw MSC bytes to request per Bridge range read")
    log_transfer.add_argument("--max-attempts", type=int, default=3, help="retry attempts for each raw MSC range read")
    log_transfer.add_argument("--no-trigger-msc", action="store_true", help="require the Bridge to already be in MSC raw mode")
    log_transfer.add_argument("--no-resume", action="store_true", help="do not use .part/.state.json resume sidecars")
    log_transfer.add_argument("--progress", action="store_true", help="print transfer progress to stderr")
    _add_json(log_transfer)
    log_decode = log_sub.add_parser("decode")
    log_decode.add_argument("--log-id", type=int, required=True)
    log_decode.add_argument("--output-dir", default="tune-data/decoded-logs")
    log_decode.add_argument("--decoder-command", default="blackbox_decode")
    _add_json(log_decode)
    log_analyze = log_sub.add_parser("analyze")
    log_analyze.add_argument("--log-id", type=int, required=True)
    log_analyze.add_argument("--csv-path")
    log_analyze.add_argument("--output-json-file", help="write the full analysis JSON to a file and keep CLI JSON concise")
    log_analyze.add_argument("--full-json", action="store_true", help="print the full analysis JSON to stdout")
    _add_json(log_analyze)
    segment_rows = log_sub.add_parser("segment-rows")
    segment_rows.add_argument("--log-id", type=int, required=True)
    segment_rows.add_argument("--segment-kind", required=True, choices=["high_rate", "throttle_punch"])
    segment_rows.add_argument("--segment-index", type=int, required=True)
    segment_rows.add_argument("--fields", help="comma-separated decoded CSV fields to return")
    segment_rows.add_argument("--pad-rows", type=int, default=0)
    segment_rows.add_argument("--max-rows", type=int, default=500)
    _add_json(segment_rows)
    log_list = log_sub.add_parser("list")
    log_list.add_argument("--build-id", type=int)
    _add_json(log_list)

    iteration = top.add_parser("iteration")
    iteration_sub = iteration.add_subparsers(dest="action", required=True)
    iteration_create = iteration_sub.add_parser("create")
    iteration_create.add_argument("--loop-id", type=int, required=True)
    iteration_create.add_argument("--log-id", type=int, action="append", default=[])
    _add_json(iteration_create)
    iteration_current = iteration_sub.add_parser("current")
    iteration_current.add_argument("--loop-id", type=int, required=True)
    _add_json(iteration_current)

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
    _add_json(task_sub.add_parser("list"))

    web = top.add_parser("web")
    web.add_argument("--host", default="127.0.0.1")
    web.add_argument("--port", type=int, default=8765)

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
    elif args.area == "log" and args.action == "import":
        log_id = import_blackbox_log(conn, Path(args.path), build_id=args.build_id, storage_dir=args.storage_dir)
        row = conn.execute("SELECT id AS log_id, parse_status, metadata_json, warnings_json FROM blackbox_logs WHERE id = ?", (log_id,)).fetchone()
        payload = _row_to_dict(row)
        payload["metadata"] = json.loads(payload.pop("metadata_json"))
        payload["warnings"] = json.loads(payload.pop("warnings_json"))
        _emit(payload, args.json)
    elif args.area == "log" and args.action == "transfer":
        def progress(event: dict[str, object]) -> None:
            print(
                f"raw={event['raw_bytes_downloaded']}/{event['requested_size']} "
                f"written={event['written_bytes']} retries={event['retries']}",
                file=sys.stderr,
            )

        payload = transfer_blackbox_log_from_bridge(
            args.bridge_host,
            output_path=Path(args.output),
            size=args.size,
            trigger_msc=not args.no_trigger_msc,
            timeout_seconds=args.timeout,
            resume=not args.no_resume,
            chunk_size=args.chunk_size,
            max_attempts=args.max_attempts,
            progress=progress if args.progress else None,
        )
        if args.json:
            _print_json(payload)
        else:
            print(payload["download"]["output_path"])
    elif args.area == "log" and args.action == "decode":
        payload = decode_imported_log(conn, args.log_id, output_dir=args.output_dir, decoder_command=args.decoder_command)
        _emit(payload, args.json)
    elif args.area == "log" and args.action == "analyze":
        payload = analyze_imported_log(conn, args.log_id, csv_path=args.csv_path)
        analysis_row = conn.execute(
            "SELECT id, analyzed_at FROM log_analyses WHERE log_id = ? ORDER BY analyzed_at DESC, id DESC LIMIT 1",
            (args.log_id,),
        ).fetchone()
        output_json_file = None
        if args.output_json_file:
            output_path = Path(args.output_json_file)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
            output_json_file = str(output_path)
        concise_payload = {
            "log_id": args.log_id,
            "analysis_id": analysis_row["id"] if analysis_row else None,
            "analyzed_at": analysis_row["analyzed_at"] if analysis_row else None,
            "row_count": payload.get("row_count"),
            "duration_seconds": payload.get("duration_seconds"),
            "quality": payload.get("quality"),
            "warnings": payload.get("warnings", []),
            "analysis_json_file": output_json_file,
            "full_analysis_stored": True,
        }
        if args.json:
            _print_json(payload if args.full_json else concise_payload)
        else:
            if output_json_file:
                print(output_json_file)
            else:
                print(payload["duration_seconds"])
    elif args.area == "log" and args.action == "segment-rows":
        fields = [field.strip() for field in args.fields.split(",")] if args.fields else None
        payload = get_segment_rows(
            conn,
            log_id=args.log_id,
            segment_kind=args.segment_kind,
            segment_index=args.segment_index,
            fields=fields,
            pad_rows=args.pad_rows,
            max_rows=args.max_rows,
        )
        if args.json:
            _print_json(payload)
        else:
            print(len(payload["rows"]))
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
    elif args.area == "diagnosis" and args.action == "record":
        diagnosis_id = record_diagnosis(conn, args.iteration_id, args.body, confidence=args.confidence, evidence=json.loads(args.evidence_json))
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
    elif args.area == "task" and args.action == "list":
        _print_json([_row_to_dict(row) for row in conn.execute("SELECT * FROM operator_tasks ORDER BY status, created_at DESC, id DESC")])
    elif args.area == "web":
        from tune.web.app import create_app
        create_app(args.db).run(host=args.host, port=args.port)
    elif args.area == "status":
        _print_json({
            "builds": conn.execute("SELECT COUNT(*) FROM builds").fetchone()[0],
            "loops_open": conn.execute("SELECT COUNT(*) FROM loops WHERE status = 'open'").fetchone()[0],
            "iterations_open": conn.execute("SELECT COUNT(*) FROM tuning_iterations WHERE status = 'open'").fetchone()[0],
            "logs": conn.execute("SELECT COUNT(*) FROM blackbox_logs").fetchone()[0],
            "open_tasks": conn.execute("SELECT COUNT(*) FROM operator_tasks WHERE status = 'open'").fetchone()[0],
            "pending_writes": conn.execute("SELECT COUNT(*) FROM tune_updates WHERE status = 'approved_pending_write'").fetchone()[0],
        })
    else:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
