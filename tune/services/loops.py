from __future__ import annotations

import json
import sqlite3


def create_loop(conn: sqlite3.Connection, build_id: int, tune_goal: str) -> int:
    cur = conn.execute(
        "INSERT INTO loops (build_id, tune_goal) VALUES (?, ?)",
        (build_id, tune_goal),
    )
    conn.commit()
    return int(cur.lastrowid)


def close_loop(conn: sqlite3.Connection, loop_id: int) -> None:
    cur = conn.execute(
        "UPDATE loops SET status = 'closed', ended_at = CURRENT_TIMESTAMP WHERE id = ? AND status = 'open'",
        (loop_id,),
    )
    conn.commit()
    if cur.rowcount == 0:
        row = conn.execute("SELECT id FROM loops WHERE id = ?", (loop_id,)).fetchone()
        if row is None:
            raise ValueError(f"Loop #{loop_id} does not exist")
        return

    for task in conn.execute("SELECT id, payload_json FROM operator_tasks WHERE status = 'open'").fetchall():
        try:
            payload = json.loads(task["payload_json"] or "{}")
        except json.JSONDecodeError:
            payload = {}
        if payload.get("loop_id") != loop_id:
            continue
        response = {
            "decision": "closed_with_loop",
            "notes": f"Operator Task closed automatically because Loop #{loop_id} was closed.",
        }
        conn.execute(
            "UPDATE operator_tasks SET status = 'resolved', response_json = ?, resolved_at = CURRENT_TIMESTAMP WHERE id = ?",
            (json.dumps(response, sort_keys=True), task["id"]),
        )
    conn.commit()
