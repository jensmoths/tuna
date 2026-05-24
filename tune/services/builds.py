from __future__ import annotations

import json
import sqlite3
from typing import Any


def create_build(conn: sqlite3.Connection, name: str, *, fc_snapshot: dict[str, Any] | None = None, operator_notes: str = "") -> int:
    cur = conn.execute(
        "INSERT INTO builds (name, fc_snapshot_json, operator_notes) VALUES (?, ?, ?)",
        (name, json.dumps(fc_snapshot or {}, sort_keys=True), operator_notes),
    )
    conn.commit()
    return int(cur.lastrowid)
