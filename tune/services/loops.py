from __future__ import annotations

import sqlite3


def create_loop(conn: sqlite3.Connection, build_id: int, tune_goal: str) -> int:
    cur = conn.execute(
        "INSERT INTO loops (build_id, tune_goal) VALUES (?, ?)",
        (build_id, tune_goal),
    )
    conn.commit()
    return int(cur.lastrowid)
