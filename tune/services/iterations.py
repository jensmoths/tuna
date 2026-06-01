from __future__ import annotations

import sqlite3

from tune.domain.rules import ensure_no_open_iteration


def create_iteration(conn: sqlite3.Connection, loop_id: int, log_ids: list[int] | None = None) -> int:
    open_row = conn.execute(
        "SELECT id FROM tuning_iterations WHERE loop_id = ? AND status = 'open'",
        (loop_id,),
    ).fetchone()
    ensure_no_open_iteration(int(open_row["id"]) if open_row else None)
    cur = conn.execute("INSERT INTO tuning_iterations (loop_id) VALUES (?)", (loop_id,))
    iteration_id = int(cur.lastrowid)
    for log_id in log_ids or []:
        conn.execute(
            "INSERT INTO iteration_logs (iteration_id, log_id) VALUES (?, ?)",
            (iteration_id, log_id),
        )
    conn.commit()
    return iteration_id


def fail_iteration(conn: sqlite3.Connection, iteration_id: int, reason: str) -> None:
    conn.execute(
        "UPDATE tuning_iterations SET status = 'failed', result = 'failed', failure_reason = ?, completed_at = CURRENT_TIMESTAMP WHERE id = ?",
        (reason, iteration_id),
    )
    conn.commit()


def complete_no_change(conn: sqlite3.Connection, iteration_id: int, reason: str) -> None:
    if not reason.strip():
        raise ValueError("No-change completion requires a reason")
    row = conn.execute("SELECT status FROM tuning_iterations WHERE id = ?", (iteration_id,)).fetchone()
    if row is None:
        raise ValueError(f"Tuning Iteration {iteration_id} does not exist")
    if row["status"] != "open":
        raise ValueError(f"Tuning Iteration {iteration_id} is not open")
    diagnosis = conn.execute("SELECT id FROM diagnoses WHERE iteration_id = ?", (iteration_id,)).fetchone()
    if diagnosis is None:
        raise ValueError("No-change completion requires a recorded Diagnosis")
    update = conn.execute("SELECT id FROM tune_updates WHERE iteration_id = ?", (iteration_id,)).fetchone()
    if update is not None:
        raise ValueError("Tuning Iteration already has a Tune Update")
    conn.execute(
        """
        UPDATE tuning_iterations
        SET status = 'completed', result = 'no_change', no_change_reason = ?, completed_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (reason.strip(), iteration_id),
    )
    conn.commit()
