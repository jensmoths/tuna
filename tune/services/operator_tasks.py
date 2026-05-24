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


def list_open_tasks(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(conn.execute("SELECT * FROM operator_tasks WHERE status = 'open' ORDER BY created_at, id"))


def resolve_task(conn: sqlite3.Connection, task_id: int, response: dict[str, Any]) -> None:
    conn.execute(
        "UPDATE operator_tasks SET status = 'resolved', response_json = ?, resolved_at = CURRENT_TIMESTAMP WHERE id = ?",
        (json.dumps(response, sort_keys=True), task_id),
    )
    conn.commit()
