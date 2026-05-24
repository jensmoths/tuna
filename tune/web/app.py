from __future__ import annotations

import json
from pathlib import Path

from flask import Flask, redirect, render_template, request, url_for

from tune.services.operator_tasks import resolve_task
from tune.services.tune_updates import approve_for_write, reject
from tune.storage import connect, init_db


def _dict(row):
    return dict(row) if row else None


def create_app(db_path: str | Path) -> Flask:
    app = Flask(__name__)
    app.config["TUNE_DB"] = str(db_path)

    def db():
        conn = connect(app.config["TUNE_DB"])
        init_db(conn)
        return conn

    @app.get("/")
    def dashboard():
        conn = db()
        counts = {
            "builds": conn.execute("SELECT COUNT(*) FROM builds").fetchone()[0],
            "open_loops": conn.execute("SELECT COUNT(*) FROM loops WHERE status = 'open'").fetchone()[0],
            "open_iterations": conn.execute("SELECT COUNT(*) FROM tuning_iterations WHERE status = 'open'").fetchone()[0],
            "open_tasks": conn.execute("SELECT COUNT(*) FROM operator_tasks WHERE status = 'open'").fetchone()[0],
            "pending_writes": conn.execute("SELECT COUNT(*) FROM tune_updates WHERE status = 'approved_pending_write'").fetchone()[0],
        }
        tasks = conn.execute("SELECT * FROM operator_tasks WHERE status = 'open' ORDER BY created_at, id LIMIT 5").fetchall()
        updates = conn.execute("SELECT * FROM tune_updates WHERE status IN ('proposed','approved_pending_write','write_failed') ORDER BY created_at DESC LIMIT 5").fetchall()
        return render_template("dashboard.html", counts=counts, tasks=tasks, updates=updates)

    @app.get("/tasks")
    def tasks():
        conn = db()
        rows = conn.execute("SELECT * FROM operator_tasks ORDER BY status, created_at DESC, id DESC").fetchall()
        return render_template("tasks.html", tasks=rows)

    @app.get("/tasks/<int:task_id>")
    def task_detail(task_id: int):
        conn = db()
        task = _dict(conn.execute("SELECT * FROM operator_tasks WHERE id = ?", (task_id,)).fetchone())
        if not task:
            return "Task not found", 404
        task["payload"] = json.loads(task["payload_json"])
        update = None
        diagnosis = None
        if task["kind"] == "review_tune_update" and "tune_update_id" in task["payload"]:
            update = _dict(conn.execute("SELECT * FROM tune_updates WHERE id = ?", (task["payload"]["tune_update_id"],)).fetchone())
            if update:
                update["settings"] = json.loads(update["settings_json"])
                diagnosis = _dict(conn.execute("SELECT * FROM diagnoses WHERE iteration_id = ?", (update["iteration_id"],)).fetchone())
        return render_template("task_detail.html", task=task, update=update, diagnosis=diagnosis)

    @app.post("/tasks/<int:task_id>/approve-write")
    def approve_write(task_id: int):
        conn = db()
        if request.form.get("safety_confirmed") != "yes":
            return "Safety confirmation is required", 400
        task = conn.execute("SELECT * FROM operator_tasks WHERE id = ?", (task_id,)).fetchone()
        if not task:
            return "Task not found", 404
        payload = json.loads(task["payload_json"])
        update_id = int(payload["tune_update_id"])
        approve_for_write(conn, update_id)
        resolve_task(conn, task_id, {"decision": "approved_for_write", "safety_confirmed": True, "tune_update_id": update_id})
        return redirect(url_for("tasks"))

    @app.post("/tasks/<int:task_id>/reject")
    def reject_update(task_id: int):
        conn = db()
        reason = request.form.get("reason", "").strip()
        if not reason:
            return "Rejection reason is required", 400
        task = conn.execute("SELECT * FROM operator_tasks WHERE id = ?", (task_id,)).fetchone()
        if not task:
            return "Task not found", 404
        payload = json.loads(task["payload_json"])
        update_id = int(payload["tune_update_id"])
        reject(conn, update_id, reason)
        resolve_task(conn, task_id, {"decision": "rejected", "reason": reason, "tune_update_id": update_id})
        return redirect(url_for("tasks"))

    @app.get("/logs")
    def logs():
        conn = db()
        rows = conn.execute("SELECT id, build_id, managed_path, sha256, size_bytes, parse_status, warnings_json, imported_at FROM blackbox_logs ORDER BY imported_at DESC, id DESC").fetchall()
        return render_template("logs.html", logs=rows)

    @app.get("/updates")
    def updates():
        conn = db()
        rows = conn.execute("SELECT * FROM tune_updates ORDER BY created_at DESC, id DESC").fetchall()
        parsed = []
        for row in rows:
            item = _dict(row)
            item["settings"] = json.loads(item["settings_json"])
            parsed.append(item)
        return render_template("updates.html", updates=parsed)

    return app
