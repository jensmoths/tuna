from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tuna_blackbox.metadata import metadata_summary
from tuna_core.cli.output import emit, emit_command_error, print_json, require_row, row_to_dict
from tuna_core.services.builds import create_build
from tuna_core.services.logs import import_blackbox_log
from tuna_core.services.loop_context import get_loop_context
from tuna_core.services.loops import create_loop
from tuna_core.services.resume import update_loop_resume_cursor


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
            {"id": log["id"], "parse_status": log["parse_status"], "latest_analysis": log.get("latest_analysis")}
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


def handle_state_command(conn: Any, args: Any) -> int | None:
    for handler in (_handle_build_command, _handle_loop_command, _handle_log_command, _handle_status_command):
        handled = handler(conn, args)
        if handled is not None:
            return handled
    return None


def _handle_build_command(conn: Any, args: Any) -> int | None:
    if args.area == "build" and args.action == "create":
        build_id = create_build(conn, args.name, fc_snapshot=json.loads(args.fc_snapshot_json), operator_notes=args.operator_notes)
        emit({"build_id": build_id}, args.json)
    elif args.area == "build" and args.action == "list":
        print_json([row_to_dict(row) for row in conn.execute("SELECT * FROM builds ORDER BY id")])
    elif args.area == "build" and args.action == "show":
        try:
            row = require_row(conn.execute("SELECT * FROM builds WHERE id = ?", (args.build_id,)).fetchone(), "Build", args.build_id)
        except ValueError as exc:
            emit_command_error(exc, args.json)
            return 1
        payload = row_to_dict(row)
        payload["fc_snapshot"] = json.loads(payload.pop("fc_snapshot_json"))
        print_json(payload)
    else:
        return None
    return 0


def _handle_loop_command(conn: Any, args: Any) -> int | None:
    if args.area == "loop" and args.action == "create":
        loop_id = create_loop(conn, args.build_id, args.tune_goal)
        emit({"loop_id": loop_id}, args.json)
    elif args.area == "loop" and args.action == "list":
        sql = "SELECT * FROM loops"
        params: tuple[Any, ...] = ()
        if args.build_id is not None:
            sql += " WHERE build_id = ?"
            params = (args.build_id,)
        print_json([row_to_dict(row) for row in conn.execute(sql + " ORDER BY id", params)])
    elif args.area == "loop" and args.action == "context":
        try:
            payload = get_loop_context(conn, args.loop_id, recent_limit=args.recent_limit)
        except ValueError as exc:
            emit_command_error(exc, args.json)
            return 1
        print_json(payload)
    elif args.area == "loop" and args.action == "status":
        try:
            payload = _loop_status_payload(conn, args.loop_id)
        except ValueError as exc:
            emit_command_error(exc, args.json)
            return 1
        print_json(payload)
    else:
        return None
    return 0


def _handle_log_command(conn: Any, args: Any) -> int | None:
    if args.area == "log" and args.action == "import":
        log_id = import_blackbox_log(conn, Path(args.path), build_id=args.build_id, storage_dir=args.storage_dir)
        row = conn.execute(
            """
            SELECT id AS log_id, build_id, managed_path, sha256, size_bytes, parse_status, imported_at, metadata_json, warnings_json
            FROM blackbox_logs
            WHERE id = ?
            """,
            (log_id,),
        ).fetchone()
        payload = row_to_dict(row)
        metadata = json.loads(payload.pop("metadata_json"))
        payload["warnings"] = json.loads(payload.pop("warnings_json"))
        payload["metadata_summary"] = metadata_summary(metadata)
        if args.metadata_json_file:
            metadata_path = Path(args.metadata_json_file)
            metadata_path.parent.mkdir(parents=True, exist_ok=True)
            metadata_path.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n")
            payload["metadata_json_file"] = str(metadata_path)
        if args.full_metadata:
            payload["metadata"] = metadata
        update_loop_resume_cursor(conn, args.loop_id, last_import={"log_id": log_id, "path": payload["managed_path"], "parse_status": payload["parse_status"]})
        emit(payload, args.json)
    elif args.area == "log" and args.action == "list":
        sql = "SELECT id, build_id, managed_path, sha256, size_bytes, parse_status, imported_at FROM blackbox_logs"
        params = ()
        if args.build_id is not None:
            sql += " WHERE build_id = ?"
            params = (args.build_id,)
        print_json([row_to_dict(row) for row in conn.execute(sql + " ORDER BY id", params)])
    else:
        return None
    return 0


def _handle_status_command(conn: Any, args: Any) -> int | None:
    if args.area == "status":
        print_json({
            "builds": conn.execute("SELECT COUNT(*) FROM builds").fetchone()[0],
            "loops_open": conn.execute("SELECT COUNT(*) FROM loops WHERE status = 'open'").fetchone()[0],
            "iterations_open": conn.execute("SELECT COUNT(*) FROM tuning_iterations WHERE status = 'open'").fetchone()[0],
            "logs": conn.execute("SELECT COUNT(*) FROM blackbox_logs").fetchone()[0],
            "open_tasks": conn.execute("SELECT COUNT(*) FROM operator_tasks WHERE status = 'open'").fetchone()[0],
            "open_notifications": conn.execute("SELECT COUNT(*) FROM operator_notifications WHERE status = 'open'").fetchone()[0],
            "pending_writes": conn.execute("SELECT COUNT(*) FROM tune_updates WHERE status = 'approved_pending_write'").fetchone()[0],
        })
    else:
        return None
    return 0
