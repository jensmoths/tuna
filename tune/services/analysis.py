from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from tune.analysis import analyze_csv_log, decode_blackbox_log


def _log_row(conn: sqlite3.Connection, log_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM blackbox_logs WHERE id = ?", (log_id,)).fetchone()
    if row is None:
        raise ValueError(f"Blackbox Log {log_id} does not exist")
    return row


def decode_imported_log(conn: sqlite3.Connection, log_id: int, *, output_dir: str | Path, decoder_command: str = "blackbox_decode") -> dict[str, object]:
    row = _log_row(conn, log_id)
    output = Path(output_dir) / f"log-{log_id}.csv"
    csv_path = decode_blackbox_log(row["managed_path"], output, decoder_command=decoder_command)
    conn.execute(
        "INSERT INTO decoded_logs (log_id, csv_path, decoder_command) VALUES (?, ?, ?)",
        (log_id, str(csv_path), decoder_command),
    )
    conn.commit()
    return {"log_id": log_id, "csv_path": str(csv_path)}


def analyze_imported_log(conn: sqlite3.Connection, log_id: int, *, csv_path: str | Path | None = None) -> dict[str, object]:
    if csv_path is None:
        decoded = conn.execute(
            "SELECT csv_path FROM decoded_logs WHERE log_id = ? ORDER BY decoded_at DESC, id DESC LIMIT 1",
            (log_id,),
        ).fetchone()
        if decoded is None:
            raise ValueError(f"Blackbox Log {log_id} has no decoded CSV; run decode first or pass csv_path")
        csv_path = decoded["csv_path"]

    summary = analyze_csv_log(csv_path)
    conn.execute(
        "INSERT INTO log_analyses (log_id, analysis_json) VALUES (?, ?)",
        (log_id, json.dumps(summary, sort_keys=True)),
    )
    conn.commit()
    return summary
