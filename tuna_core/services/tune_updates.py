from __future__ import annotations

import json
import sqlite3
from typing import Any

from tuna_core.domain.models import IterationStatus, TuneUpdateStatus
from tuna_core.domain.rules import ensure_absolute_settings, ensure_rejection_reason


def _require_update(conn: sqlite3.Connection, update_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM tune_updates WHERE id = ?", (update_id,)).fetchone()
    if row is None:
        raise ValueError(f"Tune Update {update_id} does not exist")
    return row


def _require_status(row: sqlite3.Row, allowed: set[TuneUpdateStatus]) -> None:
    status = TuneUpdateStatus(row["status"])
    if status not in allowed:
        allowed_text = ", ".join(item.value for item in sorted(allowed, key=lambda item: item.value))
        raise ValueError(f"Tune Update {row['id']} status is {status.value}; expected one of: {allowed_text}")


def propose_tune_update(conn: sqlite3.Connection, iteration_id: int, build_id: int, settings: dict[str, Any], *, cli_text: str = "") -> int:
    ensure_absolute_settings(settings)
    cur = conn.execute(
        "INSERT INTO tune_updates (iteration_id, build_id, settings_json, cli_text) VALUES (?, ?, ?, ?)",
        (iteration_id, build_id, json.dumps(settings, sort_keys=True), cli_text),
    )
    conn.commit()
    return int(cur.lastrowid)


def approve_for_write(conn: sqlite3.Connection, update_id: int) -> None:
    row = _require_update(conn, update_id)
    _require_status(row, {TuneUpdateStatus.PROPOSED})
    conn.execute(
        "UPDATE tune_updates SET status = ?, decided_at = CURRENT_TIMESTAMP WHERE id = ?",
        (TuneUpdateStatus.APPROVED_PENDING_WRITE.value, update_id),
    )
    conn.commit()


def mark_applied(conn: sqlite3.Connection, update_id: int) -> None:
    row = _require_update(conn, update_id)
    _require_status(row, {TuneUpdateStatus.APPROVED_PENDING_WRITE, TuneUpdateStatus.WRITE_FAILED})
    iteration_id = row["iteration_id"]
    conn.execute(
        "UPDATE tune_updates SET status = ?, decided_at = CURRENT_TIMESTAMP WHERE id = ?",
        (TuneUpdateStatus.APPLIED.value, update_id),
    )
    conn.execute(
        "UPDATE tuning_iterations SET status = ?, result = 'tune_update_applied', completed_at = CURRENT_TIMESTAMP WHERE id = ?",
        (IterationStatus.COMPLETED.value, iteration_id),
    )
    conn.commit()


def reject(conn: sqlite3.Connection, update_id: int, reason: str) -> None:
    ensure_rejection_reason(reason)
    row = _require_update(conn, update_id)
    _require_status(row, {TuneUpdateStatus.PROPOSED})
    iteration_id = row["iteration_id"]
    conn.execute(
        "UPDATE tune_updates SET status = ?, rejection_reason = ?, decided_at = CURRENT_TIMESTAMP WHERE id = ?",
        (TuneUpdateStatus.REJECTED.value, reason, update_id),
    )
    conn.execute(
        "UPDATE tuning_iterations SET status = ?, result = 'tune_update_rejected', completed_at = CURRENT_TIMESTAMP WHERE id = ?",
        (IterationStatus.COMPLETED.value, iteration_id),
    )
    conn.commit()


def record_application_failure(conn: sqlite3.Connection, update_id: int, failure: str) -> None:
    row = _require_update(conn, update_id)
    _require_status(row, {TuneUpdateStatus.APPROVED_PENDING_WRITE, TuneUpdateStatus.WRITE_FAILED})
    if not failure.strip():
        raise ValueError("Tune Update write failure must not be empty")
    conn.execute(
        "UPDATE tune_updates SET status = ?, application_failure = ? WHERE id = ?",
        (TuneUpdateStatus.WRITE_FAILED.value, failure.strip(), update_id),
    )
    conn.commit()
