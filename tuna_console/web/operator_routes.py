from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from flask import Flask, render_template, request

from tuna_core.services.operator_notifications import acknowledge_notification as acknowledge_operator_notification
from tuna_core.services.operator_tasks import resolve_task
from tuna_core.services.tune_updates import approve_for_write, reject
from tuna_console.web.pi_supervisor import PiRpcSupervisor


def _row_dict(row: Any) -> dict[str, Any] | None:
    return dict(row) if row else None


def register_operator_routes(
    app: Flask,
    *,
    db: Callable[[], Any],
    supervisor: Callable[[], PiRpcSupervisor],
    redirect_after_form: Callable[..., Any],
) -> None:
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

    @app.get("/tasks/<int:task_id>")
    def task_detail(task_id: int):
        conn = db()
        task = _row_dict(conn.execute("SELECT * FROM operator_tasks WHERE id = ?", (task_id,)).fetchone())
        if not task:
            return "Task not found", 404
        task["payload"] = json.loads(task["payload_json"])
        update = None
        diagnosis = None
        candidate_build = None
        builds = []
        if task["kind"] == "review_tune_update" and "tune_update_id" in task["payload"]:
            update = _row_dict(conn.execute("SELECT * FROM tune_updates WHERE id = ?", (task["payload"]["tune_update_id"],)).fetchone())
            if update:
                update["settings"] = json.loads(update["settings_json"])
                diagnosis = _row_dict(conn.execute("SELECT * FROM diagnoses WHERE iteration_id = ?", (update["iteration_id"],)).fetchone())
        if task["kind"] == "confirm_build":
            candidate_id = task["payload"].get("candidate_build_id")
            if candidate_id:
                candidate_build = _row_dict(conn.execute("SELECT id, name FROM builds WHERE id = ?", (candidate_id,)).fetchone())
            builds = conn.execute("SELECT id, name FROM builds ORDER BY name, id").fetchall()
        return render_template("task_detail.html", task=task, update=update, diagnosis=diagnosis, candidate_build=candidate_build, builds=builds)

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
        supervisor().notify_operator_task_resolved(task_id)
        return redirect_after_form("tasks")

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
        supervisor().notify_operator_task_resolved(task_id)
        return redirect_after_form("tasks")

    @app.post("/tasks/<int:task_id>/resolve-flight-capture")
    def resolve_flight_capture(task_id: int):
        conn = db()
        task = conn.execute("SELECT * FROM operator_tasks WHERE id = ?", (task_id,)).fetchone()
        if not task:
            return "Task not found", 404
        if task["kind"] != "request_flight_capture":
            return "Task is not a flight capture request", 400
        decision = request.form.get("decision", "").strip()
        if decision not in {"captured_needs_transfer", "capture_failed"}:
            return "Valid flight capture decision is required", 400
        notes = request.form.get("notes", "").strip()
        if decision == "capture_failed" and not notes:
            return "Notes are required if capture failed", 400
        resolve_task(conn, task_id, {"decision": decision, "notes": notes})
        supervisor().notify_operator_task_resolved(task_id)
        return redirect_after_form("tasks")

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
        if decision == "matches_existing_build" and build_id:
            _record_confirmed_snapshot(conn, task, int(build_id))
        resolve_task(conn, task_id, response)
        supervisor().notify_operator_task_resolved(task_id)
        return redirect_after_form("tasks")

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
        supervisor().notify_operator_task_resolved(task_id)
        return redirect_after_form("tasks")

    @app.post("/tasks/<int:task_id>/resolve-generic")
    def resolve_generic_task(task_id: int):
        conn = db()
        task = conn.execute("SELECT * FROM operator_tasks WHERE id = ?", (task_id,)).fetchone()
        if not task:
            return "Task not found", 404
        if task["status"] != "open":
            return "Task is not open", 400
        decision = request.form.get("decision", "completed").strip() or "completed"
        notes = request.form.get("notes", "").strip()
        if decision == "cannot_complete" and not notes:
            return "Operator notes are required when a task cannot be completed", 400
        resolve_task(conn, task_id, {"decision": decision, "notes": notes})
        supervisor().notify_operator_task_resolved(task_id)
        return redirect_after_form("tasks")

    @app.get("/notifications/<int:notification_id>")
    def notification_detail(notification_id: int):
        conn = db()
        notification = _row_dict(conn.execute("SELECT * FROM operator_notifications WHERE id = ?", (notification_id,)).fetchone())
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
        supervisor().notify_operator_notification_acknowledged(notification_id)
        return redirect_after_form("notifications")


def _record_confirmed_snapshot(conn: Any, task: Any, build_id: int) -> None:
    payload = json.loads(task["payload_json"] or "{}")
    snapshot = payload.get("fc_snapshot")
    if not isinstance(snapshot, dict) or not snapshot:
        return
    build = conn.execute("SELECT fc_snapshot_json FROM builds WHERE id = ?", (build_id,)).fetchone()
    current_snapshot = json.loads(build["fc_snapshot_json"] if build else "{}")
    if build and not current_snapshot:
        conn.execute(
            "UPDATE builds SET fc_snapshot_json = ? WHERE id = ?",
            (json.dumps(snapshot, sort_keys=True), build_id),
        )
        conn.commit()
