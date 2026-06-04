from __future__ import annotations

import json
from pathlib import Path

from flask import Flask, redirect, render_template, request, url_for

from tune.services.operator_notifications import acknowledge_notification as acknowledge_operator_notification
from tune.services.operator_tasks import resolve_task
from tune.services.tune_updates import approve_for_write, reject
from tune.storage import connect, init_db
from tune.web.pi_supervisor import PiRpcSupervisor


def _dict(row):
    return dict(row) if row else None


def create_app(db_path: str | Path) -> Flask:
    app = Flask(__name__)
    app.config["TUNE_DB"] = str(db_path)
    app.config.setdefault("TUNE_PI_COMMAND", "pi")
    app.config.setdefault("TUNE_WORKDIR", str(Path.cwd()))

    def db():
        conn = connect(app.config["TUNE_DB"])
        init_db(conn)
        return conn

    def supervisor() -> PiRpcSupervisor:
        existing = app.extensions.get("tuna_pi_supervisor")
        if existing is None:
            existing = PiRpcSupervisor(
                app.config["TUNE_DB"],
                cwd=app.config["TUNE_WORKDIR"],
                pi_command=app.config["TUNE_PI_COMMAND"],
            )
            app.extensions["tuna_pi_supervisor"] = existing
        return existing

    @app.get("/")
    def dashboard():
        conn = db()
        counts = {
            "builds": conn.execute("SELECT COUNT(*) FROM builds").fetchone()[0],
            "open_loops": conn.execute("SELECT COUNT(*) FROM loops WHERE status = 'open'").fetchone()[0],
            "open_iterations": conn.execute("SELECT COUNT(*) FROM tuning_iterations WHERE status = 'open'").fetchone()[0],
            "open_tasks": conn.execute("SELECT COUNT(*) FROM operator_tasks WHERE status = 'open'").fetchone()[0],
            "open_notifications": conn.execute("SELECT COUNT(*) FROM operator_notifications WHERE status = 'open'").fetchone()[0],
            "pending_writes": conn.execute("SELECT COUNT(*) FROM tune_updates WHERE status = 'approved_pending_write'").fetchone()[0],
        }
        tasks = conn.execute("SELECT * FROM operator_tasks WHERE status = 'open' ORDER BY created_at, id LIMIT 5").fetchall()
        notifications = conn.execute("SELECT * FROM operator_notifications WHERE status = 'open' ORDER BY created_at, id LIMIT 5").fetchall()
        updates = conn.execute("SELECT * FROM tune_updates WHERE status IN ('proposed','approved_pending_write','write_failed') ORDER BY created_at DESC LIMIT 5").fetchall()
        return render_template("dashboard.html", counts=counts, tasks=tasks, notifications=notifications, updates=updates)

    @app.get("/tasks")
    def tasks():
        conn = db()
        rows = conn.execute("SELECT * FROM operator_tasks ORDER BY status, created_at DESC, id DESC").fetchall()
        return render_template("tasks.html", tasks=rows)

    @app.get("/notifications")
    def notifications():
        conn = db()
        rows = conn.execute("SELECT * FROM operator_notifications ORDER BY status, created_at DESC, id DESC").fetchall()
        return render_template("notifications.html", notifications=rows)

    @app.get("/loops")
    def loops():
        conn = db()
        rows = conn.execute(
            """
            SELECT l.*, b.name AS build_name
            FROM loops l
            JOIN builds b ON b.id = l.build_id
            ORDER BY l.status = 'open' DESC, l.created_at DESC, l.id DESC
            """
        ).fetchall()
        return render_template("loops.html", loops=rows)

    @app.get("/loops/<int:loop_id>")
    def loop_detail(loop_id: int):
        conn = db()
        loop = _dict(
            conn.execute(
                """
                SELECT l.*, b.name AS build_name, b.fc_snapshot_json, b.operator_notes
                FROM loops l
                JOIN builds b ON b.id = l.build_id
                WHERE l.id = ?
                """,
                (loop_id,),
            ).fetchone()
        )
        if not loop:
            return "Loop not found", 404
        loop["fc_snapshot"] = json.loads(loop["fc_snapshot_json"])
        agent_session = _dict(conn.execute("SELECT * FROM tuning_agent_sessions WHERE loop_id = ?", (loop_id,)).fetchone())

        iteration_rows = conn.execute(
            "SELECT * FROM tuning_iterations WHERE loop_id = ? ORDER BY created_at DESC, id DESC",
            (loop_id,),
        ).fetchall()
        iterations = []
        for row in iteration_rows:
            item = _dict(row)
            diagnosis = _dict(conn.execute("SELECT * FROM diagnoses WHERE iteration_id = ?", (item["id"],)).fetchone())
            if diagnosis:
                diagnosis["evidence"] = json.loads(diagnosis["evidence_json"])
            item["diagnosis"] = diagnosis
            logs = conn.execute(
                """
                SELECT l.id, l.build_id, l.managed_path, l.parse_status, l.imported_at, il.role
                FROM iteration_logs il
                JOIN blackbox_logs l ON l.id = il.log_id
                WHERE il.iteration_id = ?
                ORDER BY l.id
                """,
                (item["id"],),
            ).fetchall()
            item["logs"] = logs
            update = _dict(conn.execute("SELECT * FROM tune_updates WHERE iteration_id = ?", (item["id"],)).fetchone())
            if update:
                update["settings"] = json.loads(update["settings_json"])
            item["update"] = update
            iterations.append(item)

        return render_template("loop_detail.html", loop=loop, iterations=iterations, agent_session=agent_session)

    @app.post("/loops/<int:loop_id>/tuning-agent/start")
    def start_tuning_agent(loop_id: int):
        conn = db()
        loop = conn.execute("SELECT id FROM loops WHERE id = ?", (loop_id,)).fetchone()
        if not loop:
            return "Loop not found", 404
        bridge_host = request.form.get("bridge_host", "").strip()
        supervisor().start_loop(loop_id, bridge_host=bridge_host)
        return redirect(url_for("loop_detail", loop_id=loop_id))

    @app.post("/loops/<int:loop_id>/tuning-agent/abort")
    def abort_tuning_agent(loop_id: int):
        supervisor().abort_loop(loop_id)
        return redirect(url_for("loop_detail", loop_id=loop_id))

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

    @app.post("/tasks/<int:task_id>/resolve-flight-capture")
    def resolve_flight_capture(task_id: int):
        conn = db()
        task = conn.execute("SELECT * FROM operator_tasks WHERE id = ?", (task_id,)).fetchone()
        if not task:
            return "Task not found", 404
        if task["kind"] != "request_flight_capture":
            return "Task is not a flight capture request", 400
        imported = request.form.get("imported") == "yes"
        notes = request.form.get("notes", "").strip()
        if not imported and not notes:
            return "Notes are required if the Blackbox Log was not imported", 400
        resolve_task(conn, task_id, {"decision": "imported" if imported else "not_imported", "notes": notes})
        return redirect(url_for("tasks"))

    @app.post("/tasks/<int:task_id>/resolve-build-confirmation")
    def resolve_build_confirmation(task_id: int):
        conn = db()
        task = conn.execute("SELECT * FROM operator_tasks WHERE id = ?", (task_id,)).fetchone()
        if not task:
            return "Task not found", 404
        if task["kind"] != "confirm_build":
            return "Task is not a Build confirmation request", 400
        decision = request.form.get("decision", "").strip()
        if decision not in {"matches_existing_build", "create_new_build", "cannot_confirm"}:
            return "Valid Build confirmation decision is required", 400
        build_id = request.form.get("build_id", "").strip()
        build_name = request.form.get("build_name", "").strip()
        notes = request.form.get("notes", "").strip()
        if decision == "matches_existing_build" and not build_id:
            return "Build id is required when confirming an existing Build", 400
        if decision == "create_new_build" and not build_name:
            return "Build name is required when requesting a new Build", 400
        if decision == "cannot_confirm" and not notes:
            return "Notes are required if the Build cannot be confirmed", 400
        response = {"decision": decision, "notes": notes}
        if build_id:
            response["build_id"] = int(build_id)
        if build_name:
            response["build_name"] = build_name
        resolve_task(conn, task_id, response)
        return redirect(url_for("tasks"))

    @app.post("/tasks/<int:task_id>/resolve-tune-goal")
    def resolve_tune_goal(task_id: int):
        conn = db()
        task = conn.execute("SELECT * FROM operator_tasks WHERE id = ?", (task_id,)).fetchone()
        if not task:
            return "Task not found", 404
        if task["kind"] != "request_tune_goal":
            return "Task is not a Tune Goal request", 400
        tune_goal = request.form.get("tune_goal", "").strip()
        if not tune_goal:
            return "Tune Goal is required", 400
        notes = request.form.get("notes", "").strip()
        resolve_task(conn, task_id, {"decision": "provided", "tune_goal": tune_goal, "notes": notes})
        return redirect(url_for("tasks"))

    @app.get("/notifications/<int:notification_id>")
    def notification_detail(notification_id: int):
        conn = db()
        notification = _dict(conn.execute("SELECT * FROM operator_notifications WHERE id = ?", (notification_id,)).fetchone())
        if not notification:
            return "Notification not found", 404
        notification["payload"] = json.loads(notification["payload_json"])
        return render_template("notification_detail.html", notification=notification)

    @app.post("/notifications/<int:notification_id>/acknowledge")
    def acknowledge_notification(notification_id: int):
        conn = db()
        notification = conn.execute("SELECT * FROM operator_notifications WHERE id = ?", (notification_id,)).fetchone()
        if not notification:
            return "Notification not found", 404
        notes = request.form.get("notes", "").strip()
        acknowledge_operator_notification(conn, notification_id, {"decision": "acknowledged", "notes": notes})
        return redirect(url_for("notifications"))

    @app.get("/logs")
    def logs():
        conn = db()
        rows = conn.execute("SELECT id, build_id, managed_path, sha256, size_bytes, parse_status, warnings_json, imported_at FROM blackbox_logs ORDER BY imported_at DESC, id DESC").fetchall()
        return render_template("logs.html", logs=rows)

    @app.get("/analysis")
    def analysis():
        conn = db()
        rows = conn.execute("""
            SELECT a.*, l.build_id, l.managed_path
            FROM log_analyses a
            JOIN blackbox_logs l ON l.id = a.log_id
            ORDER BY a.analyzed_at DESC, a.id DESC
        """).fetchall()
        analyses = []
        for row in rows:
            item = _dict(row)
            item["analysis"] = json.loads(item["analysis_json"])
            analyses.append(item)
        return render_template("analysis.html", analyses=analyses)

    @app.get("/logs/<int:log_id>/analysis")
    def log_analysis(log_id: int):
        conn = db()
        row = conn.execute("""
            SELECT a.*, l.build_id, l.managed_path
            FROM log_analyses a
            JOIN blackbox_logs l ON l.id = a.log_id
            WHERE a.log_id = ?
            ORDER BY a.analyzed_at DESC, a.id DESC
            LIMIT 1
        """, (log_id,)).fetchone()
        if not row:
            return "Analysis not found", 404
        item = _dict(row)
        item["analysis"] = json.loads(item["analysis_json"])
        return render_template("analysis_detail.html", item=item)

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
