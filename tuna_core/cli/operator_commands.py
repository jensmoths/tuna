from __future__ import annotations

import json
from typing import Any

from tuna_core.cli.output import emit, emit_command_error, loads_json_object, print_json, require_row, row_to_dict
from tuna_core.services.operator_notifications import create_blackbox_config_notification
from tuna_core.services.operator_tasks import create_build_confirmation_task, create_fcs_connection_task, create_flight_capture_task, create_task, create_tune_goal_task


def _task_payload(row: Any) -> dict[str, Any]:
    item = row_to_dict(row)
    item["payload"] = loads_json_object(item.get("payload_json"))
    item["response"] = loads_json_object(item.get("response_json")) if item.get("response_json") else None
    return item


def _notification_payload(row: Any) -> dict[str, Any]:
    item = row_to_dict(row)
    item["payload"] = loads_json_object(item.get("payload_json"))
    item["acknowledged"] = loads_json_object(item.get("acknowledged_json")) if item.get("acknowledged_json") else None
    return item


def handle_operator_command(conn: Any, args: Any) -> int | None:
    if args.area == "task" and args.action == "create":
        task_id = create_task(conn, args.kind, args.title, body=args.body, payload=json.loads(args.payload_json))
        emit({"task_id": task_id}, args.json)
    elif args.area == "task" and args.action == "request-flight-capture":
        task_id = create_flight_capture_task(conn, build_id=args.build_id, loop_id=args.loop_id, reason=args.reason, capture_goal=args.capture_goal)
        emit({"task_id": task_id, "kind": "request_flight_capture"}, args.json)
    elif args.area == "task" and args.action == "request-fcs-connection":
        task_id = create_fcs_connection_task(conn, build_id=args.build_id, loop_id=args.loop_id, bridge_host=args.bridge_host, reason=args.reason, next_step=args.next_step)
        emit({"task_id": task_id, "kind": "request_fcs_connection"}, args.json)
    elif args.area == "task" and args.action == "confirm-build":
        task_id = create_build_confirmation_task(conn, fc_snapshot=json.loads(args.fc_snapshot_json), candidate_build_id=args.candidate_build_id, loop_id=args.loop_id, reason=args.reason)
        emit({"task_id": task_id, "kind": "confirm_build"}, args.json)
    elif args.area == "task" and args.action == "request-tune-goal":
        task_id = create_tune_goal_task(conn, build_id=args.build_id, reason=args.reason)
        emit({"task_id": task_id, "kind": "request_tune_goal"}, args.json)
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
        print_json([_task_payload(row) for row in conn.execute(sql, tuple(params))])
    elif args.area == "task" and args.action == "show":
        try:
            row = require_row(conn.execute("SELECT * FROM operator_tasks WHERE id = ?", (args.task_id,)).fetchone(), "Operator Task", args.task_id)
        except ValueError as exc:
            emit_command_error(exc, args.json)
            return 1
        print_json(_task_payload(row))
    elif args.area in ("notify", "notification") and args.action == "blackbox-config-changed":
        notification_id = create_blackbox_config_notification(conn, build_id=args.build_id, loop_id=args.loop_id, settings=json.loads(args.settings_json), previous_settings=json.loads(args.previous_settings_json), reason=args.reason, impact=args.impact)
        emit({"notification_id": notification_id, "kind": "blackbox_config_changed"}, args.json)
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
        print_json([_notification_payload(row) for row in conn.execute(sql, tuple(params))])
    else:
        return None
    return 0
