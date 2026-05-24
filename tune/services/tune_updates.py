from __future__ import annotations

import json
import sqlite3
from typing import Any

from tune.domain.rules import ensure_absolute_settings, ensure_rejection_reason


def propose_tune_update(conn: sqlite3.Connection, iteration_id: int, build_id: int, settings: dict[str, Any], *, cli_text: str = "") -> int:
    ensure_absolute_settings(settings)
    cur = conn.execute(
        "INSERT INTO tune_updates (iteration_id, build_id, settings_json, cli_text) VALUES (?, ?, ?, ?)",
        (iteration_id, build_id, json.dumps(settings, sort_keys=True), cli_text),
    )
    conn.commit()
    return int(cur.lastrowid)


def approve_for_write(conn: sqlite3.Connection, update_id: int) -> None:
    conn.execute(
        "UPDATE tune_updates SET status = 'approved_pending_write', decided_at = CURRENT_TIMESTAMP WHERE id = ? AND status = 'proposed'",
        (update_id,),
    )
    conn.commit()


def mark_applied(conn: sqlite3.Connection, update_id: int) -> None:
    iteration_id = conn.execute("SELECT iteration_id FROM tune_updates WHERE id = ?", (update_id,)).fetchone()["iteration_id"]
    conn.execute(
        "UPDATE tune_updates SET status = 'applied', decided_at = CURRENT_TIMESTAMP WHERE id = ?",
        (update_id,),
    )
    conn.execute(
        "UPDATE tuning_iterations SET status = 'completed', completed_at = CURRENT_TIMESTAMP WHERE id = ?",
        (iteration_id,),
    )
    conn.commit()


def reject(conn: sqlite3.Connection, update_id: int, reason: str) -> None:
    ensure_rejection_reason(reason)
    iteration_id = conn.execute("SELECT iteration_id FROM tune_updates WHERE id = ?", (update_id,)).fetchone()["iteration_id"]
    conn.execute(
        "UPDATE tune_updates SET status = 'rejected', rejection_reason = ?, decided_at = CURRENT_TIMESTAMP WHERE id = ?",
        (reason, update_id),
    )
    conn.execute(
        "UPDATE tuning_iterations SET status = 'completed', completed_at = CURRENT_TIMESTAMP WHERE id = ?",
        (iteration_id,),
    )
    conn.commit()


def record_application_failure(conn: sqlite3.Connection, update_id: int, failure: str) -> None:
    conn.execute(
        "UPDATE tune_updates SET status = 'write_failed', application_failure = ? WHERE id = ?",
        (failure, update_id),
    )
    conn.commit()
