from __future__ import annotations

import json
import os
import time
import hashlib
from pathlib import Path

from flask import Flask, Response, redirect, render_template, request, stream_with_context, url_for
from markupsafe import Markup, escape

from tune.services.builds import create_build
from tune.services.loops import close_loop, create_loop
from tune.services.operator_notifications import acknowledge_notification as acknowledge_operator_notification
from tune.services.operator_tasks import resolve_task
from tune.services.tune_updates import approve_for_write, reject
from tune.storage import connect, init_db
from tune.web.pi_supervisor import PI_MODEL_CHOICES, THINKING_LEVEL_CHOICES, PiRpcSupervisor


def _dict(row):
    return dict(row) if row else None


def _parse_agent_trace(trace: str | None) -> list[dict[str, str]]:
    entries = []
    for raw_line in (trace or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        timestamp = ""
        message = line
        if line.startswith("[") and "] " in line:
            timestamp, message = line[1:].split("] ", 1)
        kind = "log"
        label = "Log"
        if message.startswith("Tuning Agent message: "):
            kind = "message"
            label = "Message"
            message = message.removeprefix("Tuning Agent message: ")
        elif message.startswith("tool start:") or message.startswith("tool end:"):
            kind = "tool"
            label = "Tool"
        elif "error" in message.lower() or "failed" in message.lower() or message.startswith("stderr:"):
            kind = "error"
            label = "Error"
        elif message.startswith("sent ") or message.startswith("starting ") or message.startswith("started ") or message.startswith("continuing ") or message.startswith("Operator Task") or message.startswith("Operator Notification") or message.startswith("no running"):
            kind = "supervisor"
            label = "Supervisor"
        elif message.startswith("Pi RPC") or message.startswith("agent ") or message.startswith("Tuning Agent requested"):
            kind = "rpc"
            label = "Pi RPC"
        entries.append({"timestamp": timestamp, "message": message, "kind": kind, "label": label})
    return entries


def _utc_time_tag(value: object) -> Markup:
    if value is None:
        return Markup("")
    text = str(value)
    if not text:
        return Markup("")
    iso = text.replace(" ", "T", 1)
    if not iso.endswith("Z") and "+" not in iso[10:] and "-" not in iso[10:]:
        iso += "Z"
    return Markup(f'<time class="local-time" data-utc="{escape(iso)}">{escape(text)} UTC</time>')


def _redirect_after_form(default_endpoint: str, **values):
    next_url = request.form.get("next", "").strip()
    if next_url.startswith("/") and not next_url.startswith("//"):
        return redirect(next_url)
    return redirect(url_for(default_endpoint, **values))


def _task_loop_id(conn, task: dict) -> int | None:
    payload = task.get("payload") or {}
    loop_id = payload.get("loop_id")
    if loop_id is not None:
        return int(loop_id)
    update_id = payload.get("tune_update_id")
    if update_id is None:
        return None
    row = conn.execute(
        """
        SELECT i.loop_id
        FROM tune_updates u
        JOIN tuning_iterations i ON i.id = u.iteration_id
        WHERE u.id = ?
        """,
        (int(update_id),),
    ).fetchone()
    return int(row["loop_id"]) if row else None


def _humanize_token(value: object) -> str:
    return str(value or "").replace("_", " ").strip()


def _operator_task_activity_body(task: dict) -> str:
    if task["status"] != "resolved" or not task.get("response_json"):
        return task["body"]
    try:
        response = json.loads(task["response_json"])
    except json.JSONDecodeError:
        return "Operator responded."
    if not isinstance(response, dict):
        return "Operator responded."
    decision = _humanize_token(response.get("decision")) or "responded"
    notes = str(response.get("notes") or "").strip()
    text = f"Operator {decision} task."
    if notes:
        text += f" Notes: {notes}"
    else:
        text += " Notes: none."
    return text


def _workbench_state(conn, loop_id: int, agent_process_running: bool = False) -> dict:
    loop = _dict(
        conn.execute(
            """
            SELECT l.*, b.name AS build_name
            FROM loops l
            JOIN builds b ON b.id = l.build_id
            WHERE l.id = ?
            """,
            (loop_id,),
        ).fetchone()
    )
    if not loop:
        return {}
    agent_session = _dict(conn.execute("SELECT * FROM tuning_agent_sessions WHERE loop_id = ?", (loop_id,)).fetchone())
    loops = conn.execute(
        """
        SELECT l.*, b.name AS build_name
        FROM loops l
        JOIN builds b ON b.id = l.build_id
        ORDER BY l.status = 'open' DESC, l.created_at DESC, l.id DESC
        """
    ).fetchall()
    builds = conn.execute("SELECT id, name FROM builds ORDER BY name, id").fetchall()
    tasks = []
    for row in conn.execute("SELECT * FROM operator_tasks ORDER BY created_at, id").fetchall():
        task = _dict(row)
        task["payload"] = json.loads(task["payload_json"] or "{}")
        if _task_loop_id(conn, task) == loop_id:
            tasks.append(task)
    notifications = []
    for row in conn.execute("SELECT * FROM operator_notifications ORDER BY created_at, id").fetchall():
        notification = _dict(row)
        notification["payload"] = json.loads(notification["payload_json"] or "{}")
        if notification["payload"].get("loop_id") == loop_id:
            notifications.append(notification)
    events = []
    if agent_session:
        events.append(
            {
                "kind": "agent_status",
                "type_label": "Tuning Agent",
                "title": "Tuning Agent status",
                "body": f"Tuning Agent is {agent_session['status']}.",
                "created_at": agent_session["updated_at"],
                "status_label": agent_session["status"],
            }
        )
    for task in tasks:
        events.append(
            {
                "kind": "operator_task",
                "type_label": "Operator Task",
                "title": f"#{task['id']} {task['title']}",
                "body": _operator_task_activity_body(task),
                "created_at": task["resolved_at"] or task["created_at"],
                "status": task["status"],
                "status_label": _humanize_token(task["status"]),
                "task_id": task["id"],
                "href": f"/tasks/{task['id']}",
            }
        )
    for notification in notifications:
        events.append(
            {
                "kind": "operator_notification",
                "type_label": "Operator Notification",
                "title": f"#{notification['id']} {notification['title']}",
                "body": notification["body"],
                "created_at": notification["acknowledged_at"] or notification["created_at"],
                "status": notification["status"],
                "status_label": _humanize_token(notification["status"]),
                "notification_id": notification["id"],
                "href": f"/notifications/{notification['id']}",
            }
        )
    events.sort(key=lambda event: (event.get("created_at") or "", event.get("title") or ""))
    open_tasks = [task for task in tasks if task["status"] == "open"]
    open_notifications = [notification for notification in notifications if notification["status"] == "open"]
    return {
        "loop": loop,
        "agent_session": agent_session,
        "agent_process_running": agent_process_running,
        "loops": loops,
        "builds": builds,
        "tasks": tasks,
        "notifications": notifications,
        "current_task": open_tasks[0] if open_tasks else None,
        "open_notifications": open_notifications,
        "open_task_count": len(open_tasks),
        "open_notification_count": len(open_notifications),
        "events": events,
    }


def create_app(db_path: str | Path) -> Flask:
    app = Flask(__name__)
    app.jinja_env.filters["local_time"] = _utc_time_tag
    app.config["TUNE_DB"] = str(db_path)
    app.config.setdefault("TUNE_PI_COMMAND", "pi")
    app.config.setdefault("TUNE_WORKDIR", str(Path(db_path).resolve().parent))
    app.config.setdefault("TUNE_DEFAULT_FC_CONNECTION", os.environ.get("FCS_CONNECTION", "bridge"))
    app.config.setdefault("TUNE_DEFAULT_BRIDGE_HOST", os.environ.get("FCS_BRIDGE_HOST", "tuna-bridge-usb"))
    app.config.setdefault("TUNE_DEFAULT_USB_DEVICE", os.environ.get("FCS_USB_DEVICE", ""))
    app.config.setdefault("TUNE_DEFAULT_PI_MODEL", "gpt-5.4-mini")
    app.config.setdefault("TUNE_DEFAULT_THINKING_LEVEL", "medium")
    app.config.setdefault("TUNE_VERBOSE", False)

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
                verbose=bool(app.config["TUNE_VERBOSE"]),
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

    @app.get("/builds")
    def builds():
        conn = db()
        rows = conn.execute("SELECT * FROM builds ORDER BY created_at DESC, id DESC").fetchall()
        builds = []
        for row in rows:
            item = _dict(row)
            item["fc_snapshot"] = json.loads(item["fc_snapshot_json"])
            builds.append(item)
        return render_template("builds.html", builds=builds)

    @app.post("/builds")
    def create_build_from_web():
        conn = db()
        name = request.form.get("name", "").strip()
        if not name:
            return "Build name is required", 400
        snapshot_text = request.form.get("fc_snapshot_json", "").strip()
        try:
            fc_snapshot = json.loads(snapshot_text) if snapshot_text else {}
        except json.JSONDecodeError as exc:
            return f"FC snapshot JSON is invalid: {exc}", 400
        if not isinstance(fc_snapshot, dict):
            return "FC snapshot JSON must be an object", 400
        notes = request.form.get("operator_notes", "").strip()
        build_id = create_build(conn, name, fc_snapshot=fc_snapshot, operator_notes=notes)
        return redirect(url_for("builds") + f"#build-{build_id}")

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
        builds = conn.execute("SELECT * FROM builds ORDER BY name, id").fetchall()
        return render_template("loops.html", loops=rows, builds=builds)

    @app.post("/loops")
    def create_loop_from_web():
        conn = db()
        build_id = int(request.form.get("build_id", "0"))
        tune_goal = request.form.get("tune_goal", "").strip()
        if build_id <= 0:
            return "Build is required", 400
        if not tune_goal:
            return "Tune Goal is required", 400
        loop_id = create_loop(conn, build_id, tune_goal)
        return redirect(url_for("loop_detail", loop_id=loop_id))

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
        agent_process_running = supervisor().is_loop_running(loop_id)
        agent_trace = _parse_agent_trace(agent_session.get("debug_trace") if agent_session else None)

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

        return render_template(
            "loop_detail.html",
            loop=loop,
            iterations=iterations,
            agent_session=agent_session,
            agent_process_running=agent_process_running,
            agent_trace=agent_trace,
            default_fc_connection=app.config["TUNE_DEFAULT_FC_CONNECTION"],
            default_bridge_host=app.config["TUNE_DEFAULT_BRIDGE_HOST"],
            default_usb_device=app.config["TUNE_DEFAULT_USB_DEVICE"],
            default_pi_model=app.config["TUNE_DEFAULT_PI_MODEL"],
            default_thinking_level=app.config["TUNE_DEFAULT_THINKING_LEVEL"],
            pi_model_choices=PI_MODEL_CHOICES,
            thinking_level_choices=["off", "minimal", "low", "medium", "high", "xhigh"],
        )

    @app.get("/chat")
    def workbench_index_alias():
        return redirect("/workbench")

    @app.get("/workbench")
    def workbench_index():
        conn = db()
        loop = conn.execute(
            """
            SELECT id FROM loops
            ORDER BY status = 'open' DESC, created_at DESC, id DESC
            LIMIT 1
            """
        ).fetchone()
        if loop:
            return redirect(f"/loops/{loop['id']}/workbench")
        builds = conn.execute("SELECT * FROM builds ORDER BY name, id").fetchall()
        return render_template("workbench.html", state=None, builds=builds)

    @app.get("/loops/<int:loop_id>/chat")
    def loop_workbench_alias(loop_id: int):
        return redirect(f"/loops/{loop_id}/workbench")

    @app.get("/loops/<int:loop_id>/workbench")
    def loop_workbench(loop_id: int):
        conn = db()
        state = _workbench_state(conn, loop_id, agent_process_running=supervisor().is_loop_running(loop_id))
        if not state:
            return "Loop not found", 404
        return render_template(
            "workbench.html",
            state=state,
            builds=[],
            default_fc_connection=app.config["TUNE_DEFAULT_FC_CONNECTION"],
            default_bridge_host=app.config["TUNE_DEFAULT_BRIDGE_HOST"],
            default_usb_device=app.config["TUNE_DEFAULT_USB_DEVICE"],
            default_pi_model=app.config["TUNE_DEFAULT_PI_MODEL"],
            default_thinking_level=app.config["TUNE_DEFAULT_THINKING_LEVEL"],
            pi_model_choices=PI_MODEL_CHOICES,
            thinking_level_choices=["off", "minimal", "low", "medium", "high", "xhigh"],
        )

    @app.get("/loops/<int:loop_id>/events")
    def loop_events(loop_id: int):
        once = request.args.get("once") == "1"

        @stream_with_context
        def stream():
            last_payload = ""
            while True:
                conn = db()
                state = _workbench_state(conn, loop_id, agent_process_running=supervisor().is_loop_running(loop_id))
                payload = json.dumps(
                    {
                        "agent_status": state.get("agent_session", {}).get("status") if state.get("agent_session") else "not started",
                        "html": render_template(
                            "_workbench.html",
                            state=state,
                            loop=state.get("loop"),
                            default_fc_connection=app.config["TUNE_DEFAULT_FC_CONNECTION"],
                            default_bridge_host=app.config["TUNE_DEFAULT_BRIDGE_HOST"],
                            default_usb_device=app.config["TUNE_DEFAULT_USB_DEVICE"],
                            default_pi_model=app.config["TUNE_DEFAULT_PI_MODEL"],
                            default_thinking_level=app.config["TUNE_DEFAULT_THINKING_LEVEL"],
                            pi_model_choices=PI_MODEL_CHOICES,
                            thinking_level_choices=["off", "minimal", "low", "medium", "high", "xhigh"],
                        ),
                    },
                    sort_keys=True,
                    default=str,
                )
                if payload != last_payload:
                    last_payload = payload
                    event_id = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
                    yield f"id: {event_id}\nevent: state\ndata: {payload}\n\n"
                if once:
                    break
                time.sleep(2)

        return Response(stream(), mimetype="text/event-stream")

    @app.post("/loops/<int:loop_id>/tuning-agent/start")
    def start_tuning_agent(loop_id: int):
        conn = db()
        loop = conn.execute("SELECT id FROM loops WHERE id = ?", (loop_id,)).fetchone()
        if not loop:
            return "Loop not found", 404
        fc_connection = request.form.get("fc_connection", "").strip() or app.config["TUNE_DEFAULT_FC_CONNECTION"]
        bridge_host = request.form.get("bridge_host", "").strip() or app.config["TUNE_DEFAULT_BRIDGE_HOST"]
        usb_device = request.form.get("usb_device", "").strip() or app.config["TUNE_DEFAULT_USB_DEVICE"]
        pi_model = request.form.get("pi_model", "").strip() or app.config["TUNE_DEFAULT_PI_MODEL"]
        thinking_level = request.form.get("thinking_level", "").strip() or app.config["TUNE_DEFAULT_THINKING_LEVEL"]
        if fc_connection not in {"bridge", "usb"}:
            return "Unsupported FC connection", 400
        if pi_model not in PI_MODEL_CHOICES:
            return "Unsupported Pi model", 400
        if thinking_level not in THINKING_LEVEL_CHOICES:
            return "Unsupported Pi thinking level", 400
        supervisor().start_loop(loop_id, bridge_host=bridge_host, fc_connection=fc_connection, usb_device=usb_device, pi_model=pi_model, thinking_level=thinking_level)
        return _redirect_after_form("loop_detail", loop_id=loop_id)

    @app.post("/loops/<int:loop_id>/tuning-agent/continue")
    def continue_tuning_agent(loop_id: int):
        conn = db()
        loop = conn.execute("SELECT id FROM loops WHERE id = ?", (loop_id,)).fetchone()
        if not loop:
            return "Loop not found", 404
        fc_connection = request.form.get("fc_connection", "").strip() or app.config["TUNE_DEFAULT_FC_CONNECTION"]
        bridge_host = request.form.get("bridge_host", "").strip() or app.config["TUNE_DEFAULT_BRIDGE_HOST"]
        usb_device = request.form.get("usb_device", "").strip() or app.config["TUNE_DEFAULT_USB_DEVICE"]
        pi_model = request.form.get("pi_model", "").strip() or app.config["TUNE_DEFAULT_PI_MODEL"]
        thinking_level = request.form.get("thinking_level", "").strip() or app.config["TUNE_DEFAULT_THINKING_LEVEL"]
        if fc_connection not in {"bridge", "usb"}:
            return "Unsupported FC connection", 400
        if pi_model not in PI_MODEL_CHOICES:
            return "Unsupported Pi model", 400
        if thinking_level not in THINKING_LEVEL_CHOICES:
            return "Unsupported Pi thinking level", 400
        supervisor().continue_loop(loop_id, bridge_host=bridge_host, fc_connection=fc_connection, usb_device=usb_device, pi_model=pi_model, thinking_level=thinking_level)
        return _redirect_after_form("loop_detail", loop_id=loop_id)

    @app.post("/loops/<int:loop_id>/tuning-agent/abort")
    def abort_tuning_agent(loop_id: int):
        supervisor().abort_loop(loop_id)
        return _redirect_after_form("loop_detail", loop_id=loop_id)

    @app.post("/loops/<int:loop_id>/close")
    def close_loop_from_web(loop_id: int):
        conn = db()
        try:
            close_loop(conn, loop_id)
        except ValueError:
            return "Loop not found", 404
        return redirect(url_for("loops"))

    @app.get("/tasks/<int:task_id>")
    def task_detail(task_id: int):
        conn = db()
        task = _dict(conn.execute("SELECT * FROM operator_tasks WHERE id = ?", (task_id,)).fetchone())
        if not task:
            return "Task not found", 404
        task["payload"] = json.loads(task["payload_json"])
        update = None
        diagnosis = None
        candidate_build = None
        builds = []
        if task["kind"] == "review_tune_update" and "tune_update_id" in task["payload"]:
            update = _dict(conn.execute("SELECT * FROM tune_updates WHERE id = ?", (task["payload"]["tune_update_id"],)).fetchone())
            if update:
                update["settings"] = json.loads(update["settings_json"])
                diagnosis = _dict(conn.execute("SELECT * FROM diagnoses WHERE iteration_id = ?", (update["iteration_id"],)).fetchone())
        if task["kind"] == "confirm_build":
            candidate_id = task["payload"].get("candidate_build_id")
            if candidate_id:
                candidate_build = _dict(conn.execute("SELECT id, name FROM builds WHERE id = ?", (candidate_id,)).fetchone())
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
        return _redirect_after_form("tasks")

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
        return _redirect_after_form("tasks")

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
        response = {"decision": decision, "notes": notes}
        resolve_task(conn, task_id, response)
        supervisor().notify_operator_task_resolved(task_id)
        return _redirect_after_form("tasks")

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
            payload = json.loads(task["payload_json"] or "{}")
            snapshot = payload.get("fc_snapshot")
            if isinstance(snapshot, dict) and snapshot:
                build = conn.execute("SELECT fc_snapshot_json FROM builds WHERE id = ?", (int(build_id),)).fetchone()
                current_snapshot = json.loads(build["fc_snapshot_json"] if build else "{}")
                if build and not current_snapshot:
                    conn.execute(
                        "UPDATE builds SET fc_snapshot_json = ? WHERE id = ?",
                        (json.dumps(snapshot, sort_keys=True), int(build_id)),
                    )
                    conn.commit()
        resolve_task(conn, task_id, response)
        supervisor().notify_operator_task_resolved(task_id)
        return _redirect_after_form("tasks")

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
        return _redirect_after_form("tasks")

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
        return _redirect_after_form("tasks")

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
        supervisor().notify_operator_notification_acknowledged(notification_id)
        return _redirect_after_form("notifications")

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
