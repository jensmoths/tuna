from __future__ import annotations

import json
import sqlite3

from tune.analysis.segment_rows import read_segment_rows


def get_segment_rows(
    conn: sqlite3.Connection,
    *,
    log_id: int,
    segment_kind: str,
    segment_index: int,
    fields: list[str] | None = None,
    pad_rows: int = 0,
    max_rows: int = 500,
) -> dict[str, object]:
    row = conn.execute(
        "SELECT id, analysis_json FROM log_analyses WHERE log_id = ? ORDER BY analyzed_at DESC, id DESC LIMIT 1",
        (log_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"Blackbox Log {log_id} has no analysis")
    analysis = json.loads(row["analysis_json"])
    segments = analysis.get("segments", {}).get(segment_kind)
    if segments is None:
        raise ValueError(f"Unknown segment kind: {segment_kind}")
    if not 0 <= segment_index < len(segments):
        raise ValueError(f"Segment index {segment_index} out of range for {segment_kind}")
    segment = segments[segment_index]
    ref = segment["raw_data_ref"]
    payload = read_segment_rows(
        ref["csv_path"],
        start_row=int(ref["start_row"]),
        end_row=int(ref["end_row"]),
        fields=fields,
        pad_rows=pad_rows,
        max_rows=max_rows,
    )
    payload.update(
        {
            "analysis_id": row["id"],
            "log_id": log_id,
            "segment_kind": segment_kind,
            "segment_index": segment_index,
            "segment": segment,
        }
    )
    return payload
