from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from pathlib import Path

from tune.blackbox import parse_blackbox_metadata


def import_blackbox_log(conn: sqlite3.Connection, source_path: str | Path, *, build_id: int, storage_dir: str | Path) -> int:
    source = Path(source_path)
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    existing = conn.execute("SELECT id FROM blackbox_logs WHERE sha256 = ?", (digest,)).fetchone()
    if existing:
        return int(existing["id"])

    storage = Path(storage_dir)
    storage.mkdir(parents=True, exist_ok=True)
    managed = storage / f"{digest[:16]}-{source.name}"
    shutil.copy2(source, managed)

    parsed = parse_blackbox_metadata(managed)
    cur = conn.execute(
        """
        INSERT INTO blackbox_logs
          (build_id, source_path, managed_path, sha256, size_bytes, parse_status, metadata_json, warnings_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            build_id,
            str(source),
            str(managed),
            digest,
            managed.stat().st_size,
            parsed.parse_status,
            json.dumps(parsed.metadata, sort_keys=True),
            json.dumps(parsed.warnings),
        ),
    )
    conn.commit()
    return int(cur.lastrowid)
