from __future__ import annotations

import json
import sqlite3
from typing import Any


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
    body = (
        "Fly and capture another Blackbox Log for Tuna analysis. The Tuning Agent is responsible for any "
        "flight-controller diagnostic setup through FCS before creating this task; the Operator/Pilot should "
        "focus on the flight, Post-flight Transfer, and Import."
    )
    payload = {
        "build_id": build_id,
        "loop_id": loop_id,
        "reason": reason,
        "capture_goal": capture_goal,
        "pilot_instructions": [
            "Fly in safe open space with enough altitude and battery margin",
            "Perform maneuvers relevant to the Tune Goal",
            "Avoid crashes, failsafe events, and obvious motor/output saturation when possible",
            "Land and disarm normally so the Blackbox Log is finalized",
        ],
        "post_flight_steps": [
            "Perform Post-flight Transfer through FCS",
            "Import the transferred Blackbox Log into Tuna",
            "Tell the Tuning Agent which Blackbox Log was imported, or note why capture failed",
        ],
        "expected_result": "A transferred and imported Blackbox Log associated with this Build and Loop.",
    }
    return create_task(conn, "request_flight_capture", "Capture follow-up Blackbox Log", body=body, payload=payload)


def create_build_confirmation_task(
    conn: sqlite3.Connection,
    *,
    fc_snapshot: dict[str, Any],
    reason: str = "Confirm which Build is connected before starting or continuing a Loop.",
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
    conn.execute(
        "UPDATE operator_tasks SET status = 'resolved', response_json = ?, resolved_at = CURRENT_TIMESTAMP WHERE id = ?",
        (json.dumps(response, sort_keys=True), task_id),
    )
    conn.commit()
