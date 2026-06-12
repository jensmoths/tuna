from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tuna_core.storage import connect, init_db

_UNSET = object()


class AgentSessionStore:
    """SQLite persistence boundary for Operator Console Tuning Agent sessions."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    def get_session(self, loop_id: int) -> dict[str, Any] | None:
        try:
            conn = connect(self.db_path)
        except sqlite3.Error:
            return None
        init_db(conn)
        row = conn.execute("SELECT * FROM tuning_agent_sessions WHERE loop_id = ?", (loop_id,)).fetchone()
        conn.close()
        return dict(row) if row else None

    def set_session(
        self,
        loop_id: int,
        *,
        status: str | object = _UNSET,
        bridge_host: str | object = _UNSET,
        fc_connection: str | object = _UNSET,
        usb_device: str | object = _UNSET,
        process_id: int | None | object = _UNSET,
        last_error: str | None | object = _UNSET,
        pi_session_id: str | object = _UNSET,
        pi_session_file: str | object = _UNSET,
        pi_model: str | object = _UNSET,
        thinking_level: str | object = _UNSET,
    ) -> None:
        try:
            conn = connect(self.db_path)
        except sqlite3.Error:
            return
        init_db(conn)
        conn.execute(
            "INSERT OR IGNORE INTO tuning_agent_sessions (loop_id, started_at) VALUES (?, CURRENT_TIMESTAMP)",
            (loop_id,),
        )
        updates: list[str] = []
        params: list[Any] = []
        for column, value in (
            ("status", status),
            ("bridge_host", bridge_host),
            ("fc_connection", fc_connection),
            ("usb_device", usb_device),
            ("process_id", process_id),
            ("last_error", last_error),
            ("pi_session_id", pi_session_id),
            ("pi_session_file", pi_session_file),
            ("pi_model", pi_model),
            ("thinking_level", thinking_level),
        ):
            if value is not _UNSET:
                updates.append(f"{column} = ?")
                params.append(value)
        if updates:
            updates.append("updated_at = CURRENT_TIMESTAMP")
            params.append(loop_id)
            conn.execute(f"UPDATE tuning_agent_sessions SET {', '.join(updates)} WHERE loop_id = ?", params)
        conn.commit()
        conn.close()

    def append_debug_trace(self, loop_id: int, message: str) -> None:
        timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        line = f"[{timestamp}] {message}"
        try:
            conn = connect(self.db_path)
        except sqlite3.Error:
            return
        init_db(conn)
        row = conn.execute("SELECT debug_trace FROM tuning_agent_sessions WHERE loop_id = ?", (loop_id,)).fetchone()
        existing = row["debug_trace"] if row else ""
        trace = (existing + "\n" + line).strip()[-8000:]
        conn.execute(
            "UPDATE tuning_agent_sessions SET debug_trace = ?, updated_at = CURRENT_TIMESTAMP WHERE loop_id = ?",
            (trace, loop_id),
        )
        conn.commit()
        conn.close()

    def load_loop(self, loop_id: int) -> dict[str, Any]:
        conn = connect(self.db_path)
        init_db(conn)
        row = conn.execute(
            """
            SELECT l.*, b.name AS build_name, b.fc_snapshot_json, b.operator_notes
            FROM loops l
            JOIN builds b ON b.id = l.build_id
            WHERE l.id = ?
            """,
            (loop_id,),
        ).fetchone()
        conn.close()
        if row is None:
            raise ValueError(f"Loop not found: {loop_id}")
        return dict(row)

    def load_task(self, task_id: int) -> dict[str, Any] | None:
        conn = connect(self.db_path)
        init_db(conn)
        row = conn.execute("SELECT * FROM operator_tasks WHERE id = ?", (task_id,)).fetchone()
        conn.close()
        return dict(row) if row else None

    def load_notification(self, notification_id: int) -> dict[str, Any] | None:
        conn = connect(self.db_path)
        init_db(conn)
        row = conn.execute("SELECT * FROM operator_notifications WHERE id = ?", (notification_id,)).fetchone()
        conn.close()
        return dict(row) if row else None

    def loop_ids_for_task(self, task: dict[str, Any]) -> list[int]:
        loop_id = loop_id_from_payload(task.get("payload_json"))
        if loop_id is not None:
            return [loop_id]
        try:
            payload = json.loads(task.get("payload_json") or "{}")
        except json.JSONDecodeError:
            payload = {}
        update_id = payload.get("tune_update_id")
        if update_id is None:
            return []
        conn = connect(self.db_path)
        init_db(conn)
        row = conn.execute(
            """
            SELECT i.loop_id
            FROM tune_updates u
            JOIN tuning_iterations i ON i.id = u.iteration_id
            WHERE u.id = ?
            """,
            (int(update_id),),
        ).fetchone()
        conn.close()
        return [int(row["loop_id"])] if row else []


def loop_id_from_payload(payload_json: str | None) -> int | None:
    try:
        payload = json.loads(payload_json or "{}")
    except json.JSONDecodeError:
        return None
    loop_id = payload.get("loop_id")
    return int(loop_id) if loop_id is not None else None
