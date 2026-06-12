from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from flask import Flask, render_template


def _row_dict(row: Any) -> dict[str, Any] | None:
    return dict(row) if row else None


def register_artifact_routes(app: Flask, *, db: Callable[[], Any]) -> None:
    @app.get("/logs")
    def logs():
        conn = db()
        rows = conn.execute(
            """
            SELECT id, build_id, managed_path, sha256, size_bytes, parse_status, warnings_json, imported_at
            FROM blackbox_logs
            ORDER BY imported_at DESC, id DESC
            """
        ).fetchall()
        return render_template("logs.html", logs=rows)

    @app.get("/analysis")
    def analysis():
        conn = db()
        rows = conn.execute(
            """
            SELECT a.*, l.build_id, l.managed_path
            FROM log_analyses a
            JOIN blackbox_logs l ON l.id = a.log_id
            ORDER BY a.analyzed_at DESC, a.id DESC
            """
        ).fetchall()
        analyses = []
        for row in rows:
            item = _row_dict(row)
            item["analysis"] = json.loads(item["analysis_json"])
            analyses.append(item)
        return render_template("analysis.html", analyses=analyses)

    @app.get("/logs/<int:log_id>/analysis")
    def log_analysis(log_id: int):
        conn = db()
        row = conn.execute(
            """
            SELECT a.*, l.build_id, l.managed_path
            FROM log_analyses a
            JOIN blackbox_logs l ON l.id = a.log_id
            WHERE a.log_id = ?
            ORDER BY a.analyzed_at DESC, a.id DESC
            LIMIT 1
            """,
            (log_id,),
        ).fetchone()
        if not row:
            return "Analysis not found", 404
        item = _row_dict(row)
        item["analysis"] = json.loads(item["analysis_json"])
        return render_template("analysis_detail.html", item=item)

    @app.get("/updates")
    def updates():
        conn = db()
        rows = conn.execute("SELECT * FROM tune_updates ORDER BY created_at DESC, id DESC").fetchall()
        parsed = []
        for row in rows:
            item = _row_dict(row)
            item["settings"] = json.loads(item["settings_json"])
            parsed.append(item)
        return render_template("updates.html", updates=parsed)
