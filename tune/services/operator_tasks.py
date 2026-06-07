from __future__ import annotations

import json
import sqlite3
from typing import Any

from tune.services.resume import update_loop_resume_cursor


def create_task(conn: sqlite3.Connection, kind: str, title: str, *, body: str = "", payload: dict[str, Any] | None = None) -> int:
    cur = conn.execute(
        "INSERT INTO operator_tasks (kind, title, body, payload_json) VALUES (?, ?, ?, ?)",
        (kind, title, body, json.dumps(payload or {}, sort_keys=True)),
    )
    conn.commit()
    return int(cur.lastrowid)


def create_flight_capture_task(
    conn: sqlite3.Connection,
    *,
    build_id: int | None = None,
    loop_id: int | None = None,
    reason: str = "Need another Blackbox Log for tuning evidence.",
    capture_goal: str = "Capture a useful follow-up Blackbox Log for the current Tune Goal.",
) -> int:
    operator_message = _flight_capture_operator_message(capture_goal)
    body = operator_message
    payload = {
        "build_id": build_id,
        "loop_id": loop_id,
        "reason": reason,
        "capture_goal": capture_goal,
        "operator_message": operator_message,
        "pilot_instructions": [
            "Fly in safe open space with enough altitude and battery margin",
            "Perform maneuvers relevant to the Tune Goal",
            "Avoid crashes, failsafe events, and obvious motor/output saturation when possible",
            "Land and disarm normally so the Blackbox Log is finalized",
        ],
        "operator_post_flight_steps": [
            "Land and disarm normally so the Blackbox Log is finalized",
            "Leave the FC/Bridge connected or reconnect it when possible",
            "Tell the Tuning Agent whether the Blackbox Log was captured, or note why capture failed",
        ],
        "tuning_agent_follow_up_steps": [
            "Perform Post-flight Transfer through FCS",
            "Import the transferred Blackbox Log into Tuna",
            "Record which Blackbox Log was imported, or decide the next Loop action if capture failed",
        ],
        "expected_result": "A completed flight capture response. The Tuning Agent then performs Post-flight Transfer and Import.",
        "decision_options": [
            "captured_needs_transfer",
            "capture_failed",
        ],
        "required_response": {
            "captured_needs_transfer": ["notes"],
            "capture_failed": ["notes"],
        },
    }
    return create_task(conn, "request_flight_capture", "Capture follow-up Blackbox Log", body=body, payload=payload)


def _flight_capture_operator_message(capture_goal: str) -> str:
    return "\n".join(
        [
            f"Capture goal: {capture_goal}",
            "",
            "Steps:",
            "1. Pilot: fly the requested maneuvers for the capture goal.",
            "2. Pilot: land and disarm normally to finalize the Blackbox Log.",
            "3. Operator: keep or reconnect the FC/Bridge connection.",
            "4. Operator: resolve this task as captured or failed, with notes.",
        ]
    )


def create_fcs_connection_task(
    conn: sqlite3.Connection,
    *,
    build_id: int | None = None,
    loop_id: int | None = None,
    bridge_host: str = "tuna-bridge-usb",
    reason: str = "FCS Bridge connection is required before the Tuning Agent can continue.",
    next_step: str = "Restore the FC/Bridge connection in USB CDC/MSP mode.",
) -> int:
    payload = {
        "build_id": build_id,
        "loop_id": loop_id,
        "bridge_host": bridge_host,
        "reason": reason,
        "next_step": next_step,
        "decision_options": ["completed", "cannot_complete"],
        "required_response": {
            "completed": ["notes"],
            "cannot_complete": ["notes"],
        },
    }
    return create_task(
        conn,
        "request_fcs_connection",
        "Restore FCS connection for transfer",
        body="Reconnect or power-cycle the FC/Bridge so Tuna can continue FCS operations.",
        payload=payload,
    )


def create_build_confirmation_task(
    conn: sqlite3.Connection,
    *,
    fc_snapshot: dict[str, Any],
    reason: str = "",
    candidate_build_id: int | None = None,
) -> int:
    body = (
        "Confirm whether the flight-controller snapshot belongs to an existing Build or should be recorded "
        "as a new Build. The Tuning Agent extracted the snapshot through FCS; the Operator should answer "
        "based on the physical aircraft and any tuning-relevant hardware changes."
    )
    payload = {
        "candidate_build_id": candidate_build_id,
        "fc_snapshot": fc_snapshot,
        "reason": reason,
        "decision_options": [
            "matches_existing_build",
            "create_new_build",
            "cannot_confirm",
        ],
        "required_response": {
            "matches_existing_build": ["build_id"],
            "create_new_build": ["build_name"],
            "cannot_confirm": ["notes"],
        },
    }
    return create_task(conn, "confirm_build", "Confirm connected Build", body=body, payload=payload)


def create_tune_goal_task(
    conn: sqlite3.Connection,
    *,
    build_id: int | None = None,
    reason: str = "Define the Tune Goal before starting a Loop.",
) -> int:
    body = (
        "Describe the Tune Goal for this Build. The Tuning Agent will use this response to create or continue "
        "a Loop, but the Operator Console only records the Operator response."
    )
    payload = {
        "build_id": build_id,
        "reason": reason,
        "prompt": "What tuning outcome should Tuna pursue for this Build and flying style?",
        "examples": [
            "Reduce propwash while preserving freestyle response",
            "Improve setpoint tracking for racing lines",
            "Reduce motor heat and D-term noise before increasing response",
        ],
        "required_response": ["tune_goal"],
    }
    return create_task(conn, "request_tune_goal", "Define Tune Goal", body=body, payload=payload)


def list_open_tasks(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(conn.execute("SELECT * FROM operator_tasks WHERE status = 'open' ORDER BY created_at, id"))


def resolve_task(conn: sqlite3.Connection, task_id: int, response: dict[str, Any]) -> None:
    task = conn.execute("SELECT * FROM operator_tasks WHERE id = ?", (task_id,)).fetchone()
    if task is None:
        raise ValueError(f"Operator Task {task_id} does not exist")
    conn.execute(
        "UPDATE operator_tasks SET status = 'resolved', response_json = ?, resolved_at = CURRENT_TIMESTAMP WHERE id = ?",
        (json.dumps(response, sort_keys=True), task_id),
    )
    conn.commit()
    payload = json.loads(task["payload_json"] or "{}")
    update_loop_resume_cursor(
        conn,
        payload.get("loop_id"),
        last_resolved_operator_task={
            "id": task_id,
            "kind": task["kind"],
            "response": response,
        },
    )
