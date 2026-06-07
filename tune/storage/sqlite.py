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
    _migrate_operator_notifications(conn)
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
          pi_model TEXT NOT NULL DEFAULT '',
          thinking_level TEXT NOT NULL DEFAULT '',
          process_id INTEGER,
          last_error TEXT,
          debug_trace TEXT NOT NULL DEFAULT '',
          resume_cursor_json TEXT NOT NULL DEFAULT '{}',
          started_at TEXT,
          updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(tuning_agent_sessions)")}
    if "pi_model" not in columns:
        conn.execute("ALTER TABLE tuning_agent_sessions ADD COLUMN pi_model TEXT NOT NULL DEFAULT ''")
    if "thinking_level" not in columns:
        conn.execute("ALTER TABLE tuning_agent_sessions ADD COLUMN thinking_level TEXT NOT NULL DEFAULT ''")
    if "debug_trace" not in columns:
        conn.execute("ALTER TABLE tuning_agent_sessions ADD COLUMN debug_trace TEXT NOT NULL DEFAULT ''")
    if "resume_cursor_json" not in columns:
        conn.execute("ALTER TABLE tuning_agent_sessions ADD COLUMN resume_cursor_json TEXT NOT NULL DEFAULT '{}'")


def _migrate_operator_notifications(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS operator_notifications (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          kind TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'open',
          title TEXT NOT NULL,
          body TEXT NOT NULL DEFAULT '',
          payload_json TEXT NOT NULL DEFAULT '{}',
          acknowledged_json TEXT,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          acknowledged_at TEXT
        )
        """
    )
    task_columns = {row["name"] for row in conn.execute("PRAGMA table_info(operator_tasks)")}
    if not task_columns:
        return
    conn.execute("DELETE FROM operator_tasks WHERE kind LIKE 'notify_%'")
