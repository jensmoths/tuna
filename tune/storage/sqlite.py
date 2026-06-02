from __future__ import annotations

import sqlite3
from pathlib import Path


def connect(path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    schema = Path(__file__).with_name("schema.sql").read_text()
    conn.executescript(schema)
    _migrate_tuning_iterations(conn)
    _migrate_tuning_agent_sessions(conn)
    conn.commit()


def _migrate_tuning_iterations(conn: sqlite3.Connection) -> None:
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(tuning_iterations)")}
    if "result" not in columns:
        conn.execute("ALTER TABLE tuning_iterations ADD COLUMN result TEXT NOT NULL DEFAULT ''")
    if "no_change_reason" not in columns:
        conn.execute("ALTER TABLE tuning_iterations ADD COLUMN no_change_reason TEXT NOT NULL DEFAULT ''")


def _migrate_tuning_agent_sessions(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS tuning_agent_sessions (
          loop_id INTEGER PRIMARY KEY REFERENCES loops(id),
          pi_session_id TEXT,
          pi_session_file TEXT,
          status TEXT NOT NULL DEFAULT 'Idle',
          bridge_host TEXT NOT NULL DEFAULT '',
          process_id INTEGER,
          last_error TEXT,
          started_at TEXT,
          updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
