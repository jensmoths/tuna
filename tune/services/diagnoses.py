from __future__ import annotations

import json
import sqlite3
from typing import Any


def record_diagnosis(conn: sqlite3.Connection, iteration_id: int, body: str, *, confidence: str = "", evidence: dict[str, Any] | None = None) -> int:
    cur = conn.execute(
        "INSERT INTO diagnoses (iteration_id, body, confidence, evidence_json) VALUES (?, ?, ?, ?)",
        (iteration_id, body, confidence, json.dumps(evidence or {}, sort_keys=True)),
    )
    conn.commit()
    return int(cur.lastrowid)
