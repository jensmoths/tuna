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


def create_chirp_capture_task(
    conn: sqlite3.Connection,
    *,
    build_id: int | None = None,
    loop_id: int | None = None,
    reason: str = "Normal Blackbox Logs do not provide enough control-loop frequency-response evidence.",
) -> int:
    body = (
        "Capture a diagnostic chirp Blackbox Log. Setup: use CHIRP-enabled Betaflight firmware, "
        "set debug_mode = CHIRP, enable high-resolution Blackbox logging when available, and assign CHIRP to an AUX switch. "
        "Flight: the Pilot should fly in open space, run full roll, pitch, and yaw chirps by toggling the CHIRP switch, "
        "avoid motor saturation, then transfer and Import the Blackbox Log into Tuna."
    )
    payload = {
        "build_id": build_id,
        "loop_id": loop_id,
        "reason": reason,
        "setup_checklist": [
            "Firmware has CHIRP support",
            "debug_mode = CHIRP",
            "High-resolution Blackbox logging enabled when available",
            "CHIRP assigned to an AUX switch",
        ],
        "pilot_instructions": [
            "Fly in open space with enough altitude and battery margin",
            "Run one full chirp for roll, pitch, and yaw; toggling CHIRP off/on cycles axes",
            "Prefer two full axis cycles if safe",
            "Avoid motor/output saturation during chirp",
        ],
        "expected_analysis": "After Import/decode/analyze, chirp_analysis.available should be true with usable roll, pitch, and yaw segments.",
    }
    return create_task(conn, "request_chirp_capture", "Capture chirp diagnostic Blackbox Log", body=body, payload=payload)


def list_open_tasks(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(conn.execute("SELECT * FROM operator_tasks WHERE status = 'open' ORDER BY created_at, id"))


def resolve_task(conn: sqlite3.Connection, task_id: int, response: dict[str, Any]) -> None:
    conn.execute(
        "UPDATE operator_tasks SET status = 'resolved', response_json = ?, resolved_at = CURRENT_TIMESTAMP WHERE id = ?",
        (json.dumps(response, sort_keys=True), task_id),
    )
    conn.commit()
