from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any

from tuna_blackbox import analyze_csv_log, decode_blackbox_log
from tuna_blackbox.analysis_views import recording_summary


def _log_row(conn: sqlite3.Connection, log_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM blackbox_logs WHERE id = ?", (log_id,)).fetchone()
    if row is None:
        raise ValueError(f"Blackbox Log {log_id} does not exist")
    return row


def _recording_index(path: str | Path) -> int | None:
    match = re.search(r"\.(\d+)\.csv$", Path(path).name)
    return int(match.group(1)) if match else None


def _decoded_recording_paths(source_path: str | Path, selected_csv: str | Path) -> list[Path]:
    source = Path(source_path)
    selected = Path(selected_csv)
    paths = sorted(selected.parent.glob(f"{source.stem}*.csv"))
    if selected not in paths and selected.exists():
        paths.append(selected)
    siblings = [path for path in paths if path != selected]
    return siblings + [selected]


def decode_imported_log(conn: sqlite3.Connection, log_id: int, *, output_dir: str | Path, decoder_command: str = "blackbox_decode") -> dict[str, object]:
    row = _log_row(conn, log_id)
    output = Path(output_dir) / f"log-{log_id}.csv"
    csv_path = decode_blackbox_log(row["managed_path"], output, decoder_command=decoder_command)
    recording_paths = _decoded_recording_paths(row["managed_path"], csv_path)
    recordings = []
    for path in recording_paths:
        conn.execute(
            "INSERT INTO decoded_logs (log_id, csv_path, decoder_command) VALUES (?, ?, ?)",
            (log_id, str(path), decoder_command),
        )
        recordings.append({"csv_path": str(path), "recording_index": _recording_index(path)})
    conn.commit()
    return {"log_id": log_id, "csv_path": str(csv_path), "recordings": recordings}


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


def latest_analysis(conn: sqlite3.Connection, log_id: int) -> tuple[int, str, dict[str, Any]]:
    row = conn.execute(
        "SELECT id, analyzed_at, analysis_json FROM log_analyses WHERE log_id = ? ORDER BY analyzed_at DESC, id DESC LIMIT 1",
        (log_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"Blackbox Log {log_id} has no analysis")
    return int(row["id"]), str(row["analyzed_at"]), json.loads(row["analysis_json"])


def list_recordings(conn: sqlite3.Connection, log_id: int, *, sort: str = "decoded", limit: int | None = None) -> dict[str, Any]:
    _log_row(conn, log_id)
    decoded_rows = conn.execute(
        "SELECT id, csv_path, decoder_command, decoded_at FROM decoded_logs WHERE log_id = ? ORDER BY id",
        (log_id,),
    ).fetchall()
    analyses = conn.execute(
        "SELECT id, analyzed_at, analysis_json FROM log_analyses WHERE log_id = ? ORDER BY analyzed_at DESC, id DESC",
        (log_id,),
    ).fetchall()
    analyses_by_csv: dict[str, tuple[Any, dict[str, Any]]] = {}
    for row in analyses:
        analysis = json.loads(row["analysis_json"])
        csv_path = analysis.get("csv_path")
        if isinstance(csv_path, str) and csv_path not in analyses_by_csv:
            analyses_by_csv[csv_path] = (row, analysis)

    recordings = []
    for row in decoded_rows:
        csv_path = row["csv_path"]
        analysis_row, analysis = analyses_by_csv.get(csv_path, (None, None))
        item = {
            "decoded_log_id": row["id"],
            "csv_path": csv_path,
            "recording_index": _recording_index(csv_path),
            "decoded_at": row["decoded_at"],
            "decoder_command": row["decoder_command"],
            "analysis_id": analysis_row["id"] if analysis_row else None,
            "analyzed_at": analysis_row["analyzed_at"] if analysis_row else None,
            "analysis": recording_summary(analysis) if analysis else None,
        }
        recordings.append(item)

    if sort in {"start-time", "start_time"}:
        recordings.sort(key=lambda item: ((item.get("analysis") or {}).get("start_time_seconds") is None, (item.get("analysis") or {}).get("start_time_seconds") or 0.0, item["decoded_log_id"]))
    elif sort == "activity":
        recordings.sort(key=lambda item: ((item.get("analysis") or {}).get("detected_active_rows") or 0), reverse=True)
    total_recording_count = len(recordings)
    if limit is not None:
        recordings = recordings[:limit]
    return {"log_id": log_id, "recordings": recordings, "recording_count": len(recordings), "total_recording_count": total_recording_count}
