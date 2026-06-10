from __future__ import annotations

import json
import sqlite3
from typing import Any


def _loads(raw: str | None, default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default


def _row(row: sqlite3.Row | None) -> dict[str, Any]:
    return dict(row) if row is not None else {}


def _task_payload(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    if kind == "request_flight_capture":
        return {
            key: payload.get(key)
            for key in ("build_id", "loop_id", "reason", "capture_goal", "expected_result")
            if key in payload
        }
    if kind == "confirm_build":
        return {
            key: payload.get(key)
            for key in ("candidate_build_id", "reason", "fc_snapshot")
            if key in payload
        }
    if kind == "request_tune_goal":
        return {key: payload.get(key) for key in ("build_id", "reason", "prompt") if key in payload}
    return payload


def _task_item(row: sqlite3.Row) -> dict[str, Any]:
    item = _row(row)
    payload = _loads(item.pop("payload_json", None), {})
    response = _loads(item.pop("response_json", None), None)
    return {
        "id": item["id"],
        "kind": item["kind"],
        "status": item["status"],
        "title": item["title"],
        "created_at": item["created_at"],
        "resolved_at": item["resolved_at"],
        "payload": _task_payload(item["kind"], payload),
        "response": response,
    }


def _notification_item(row: sqlite3.Row) -> dict[str, Any]:
    item = _row(row)
    payload = _loads(item.pop("payload_json", None), {})
    acknowledged = _loads(item.pop("acknowledged_json", None), None)
    return {
        "id": item["id"],
        "kind": item["kind"],
        "status": item["status"],
        "title": item["title"],
        "created_at": item["created_at"],
        "acknowledged_at": item["acknowledged_at"],
        "payload": payload,
        "acknowledged": acknowledged,
    }


def _belongs_to_loop(payload: dict[str, Any], *, loop_id: int, build_id: int) -> bool:
    if payload.get("loop_id") == loop_id:
        return True
    if payload.get("build_id") == build_id:
        return True
    if payload.get("candidate_build_id") == build_id:
        return True
    return False


def _latest_analysis(conn: sqlite3.Connection, log_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT id, analyzed_at, analysis_json
        FROM log_analyses
        WHERE log_id = ?
        ORDER BY analyzed_at DESC, id DESC
        LIMIT 1
        """,
        (log_id,),
    ).fetchone()
    if row is None:
        return None
    analysis = _loads(row["analysis_json"], {})
    return {
        "analysis_id": row["id"],
        "analyzed_at": row["analyzed_at"],
        "row_count": analysis.get("row_count"),
        "duration_seconds": analysis.get("duration_seconds"),
        "quality": analysis.get("quality"),
        "warnings": analysis.get("warnings", []),
    }


def get_loop_context(conn: sqlite3.Connection, loop_id: int, *, recent_limit: int = 5) -> dict[str, Any]:
    loop_row = conn.execute(
        """
        SELECT l.*, b.name AS build_name, b.fc_snapshot_json, b.operator_notes
        FROM loops l
        JOIN builds b ON b.id = l.build_id
        WHERE l.id = ?
        """,
        (loop_id,),
    ).fetchone()
    if loop_row is None:
        raise ValueError(f"Loop {loop_id} does not exist")

    loop = _row(loop_row)
    build_id = int(loop["build_id"])
    build = {
        "id": build_id,
        "name": loop.pop("build_name"),
        "fc_snapshot": _loads(loop.pop("fc_snapshot_json"), {}),
        "operator_notes": loop.pop("operator_notes"),
    }

    current_iteration = _row(
        conn.execute(
            "SELECT * FROM tuning_iterations WHERE loop_id = ? AND status = 'open'",
            (loop_id,),
        ).fetchone()
    )

    logs = []
    for row in conn.execute(
        """
        SELECT id, build_id, managed_path, sha256, size_bytes, parse_status, imported_at
        FROM blackbox_logs
        WHERE build_id = ?
        ORDER BY imported_at DESC, id DESC
        """,
        (build_id,),
    ):
        item = _row(row)
        item["latest_analysis"] = _latest_analysis(conn, int(item["id"]))
        logs.append(item)

    tasks = []
    for row in conn.execute("SELECT * FROM operator_tasks ORDER BY created_at DESC, id DESC LIMIT 50"):
        payload = _loads(row["payload_json"], {})
        if _belongs_to_loop(payload, loop_id=loop_id, build_id=build_id):
            tasks.append(_task_item(row))
    open_tasks = [task for task in tasks if task["status"] == "open"]
    recent_tasks = [task for task in tasks if task["status"] != "open"][:recent_limit]

    notifications = []
    for row in conn.execute("SELECT * FROM operator_notifications ORDER BY created_at DESC, id DESC LIMIT 50"):
        payload = _loads(row["payload_json"], {})
        if _belongs_to_loop(payload, loop_id=loop_id, build_id=build_id):
            notifications.append(_notification_item(row))
    open_notifications = [item for item in notifications if item["status"] == "open"]
    recent_notifications = [item for item in notifications if item["status"] != "open"][:recent_limit]

    pending_writes = conn.execute(
        """
        SELECT COUNT(*)
        FROM tune_updates u
        JOIN tuning_iterations i ON i.id = u.iteration_id
        WHERE i.loop_id = ? AND u.status IN ('approved_pending_write', 'write_failed')
        """,
        (loop_id,),
    ).fetchone()[0]

    session = conn.execute(
        "SELECT status, bridge_host, resume_cursor_json, updated_at FROM tuning_agent_sessions WHERE loop_id = ?",
        (loop_id,),
    ).fetchone()

    return {
        "loop": loop,
        "build": build,
        "current_iteration": current_iteration,
        "logs": logs,
        "open_tasks": open_tasks,
        "recent_tasks": recent_tasks,
        "open_notifications": open_notifications,
        "recent_notifications": recent_notifications,
        "pending_writes": pending_writes,
        "resume": {
            "session": _row(session) if session else {},
            "cursor": _loads(session["resume_cursor_json"] if session else None, {}),
        },
    }
