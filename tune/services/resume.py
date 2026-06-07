from __future__ import annotations

import json
import sqlite3
from typing import Any


def _loads_object(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def update_loop_resume_cursor(conn: sqlite3.Connection, loop_id: int | None, **updates: Any) -> None:
    if loop_id is None:
        return
    if conn.execute("SELECT 1 FROM loops WHERE id = ?", (loop_id,)).fetchone() is None:
        return
    clean_updates = {key: value for key, value in updates.items() if value is not None}
    if not clean_updates:
        return

    row = conn.execute(
        "SELECT resume_cursor_json FROM tuning_agent_sessions WHERE loop_id = ?",
        (loop_id,),
    ).fetchone()
    cursor = _loads_object(row["resume_cursor_json"] if row else None)
    cursor.update(clean_updates)
    cursor_json = json.dumps(cursor, sort_keys=True)

    if row is None:
        conn.execute(
            """
            INSERT INTO tuning_agent_sessions (loop_id, resume_cursor_json, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            """,
            (loop_id, cursor_json),
        )
    else:
        conn.execute(
            """
            UPDATE tuning_agent_sessions
            SET resume_cursor_json = ?, updated_at = CURRENT_TIMESTAMP
            WHERE loop_id = ?
            """,
            (cursor_json, loop_id),
        )
    conn.commit()
