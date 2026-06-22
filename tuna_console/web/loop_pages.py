from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from typing import Any

from flask import Flask, Response, redirect, render_template, request, stream_with_context, url_for

from tuna_core.services.builds import create_build
from tuna_core.services.loops import create_loop
from tuna_console.web.agent_trace import parse_agent_trace
from tuna_console.web.pi_supervisor import PI_MODEL_CHOICES, PiRpcSupervisor
from tuna_console.web.workbench_state import workbench_state

THINKING_LEVEL_CHOICES = ["off", "minimal", "low", "medium", "high", "xhigh"]


def _row_dict(row: Any) -> dict[str, Any] | None:
    return dict(row) if row else None


def register_loop_page_routes(
    app: Flask,
    *,
    db: Callable[[], Any],
    supervisor: Callable[[], PiRpcSupervisor],
) -> None:
    @app.get("/builds")
    def builds():
        conn = db()
        rows = conn.execute("SELECT * FROM builds ORDER BY created_at DESC, id DESC").fetchall()
        builds = []
        for row in rows:
            item = _row_dict(row)
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
        next_url = request.form.get("next", "").strip()
        if next_url.startswith("/") and not next_url.startswith("//"):
            return redirect(next_url)
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
        return redirect(url_for("loop_workbench", loop_id=loop_id))

    @app.get("/loops/<int:loop_id>")
    def loop_detail(loop_id: int):
        conn = db()
        loop = _row_dict(
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
        agent_session = _row_dict(conn.execute("SELECT * FROM tuning_agent_sessions WHERE loop_id = ?", (loop_id,)).fetchone())
        agent_trace = parse_agent_trace(agent_session.get("debug_trace") if agent_session else None)
        return render_template(
            "loop_detail.html",
            loop=loop,
            iterations=_loop_iterations(conn, loop_id),
            agent_session=agent_session,
            agent_process_running=supervisor().is_loop_running(loop_id),
            agent_trace=agent_trace,
            **_agent_template_defaults(app),
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
        state = workbench_state(conn, loop_id, agent_process_running=supervisor().is_loop_running(loop_id))
        if not state:
            return "Loop not found", 404
        return render_template("workbench.html", state=state, builds=[], **_agent_template_defaults(app))

    @app.get("/loops/<int:loop_id>/events")
    def loop_events(loop_id: int):
        once = request.args.get("once") == "1"

        @stream_with_context
        def stream():
            last_payload = ""
            while True:
                conn = db()
                state = workbench_state(conn, loop_id, agent_process_running=supervisor().is_loop_running(loop_id))
                payload = json.dumps(
                    {
                        "agent_status": state.get("agent_session", {}).get("status") if state.get("agent_session") else "not started",
                        "html": render_template("_workbench.html", state=state, loop=state.get("loop"), **_agent_template_defaults(app)),
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


def _agent_template_defaults(app: Flask) -> dict[str, Any]:
    return {
        "default_fc_connection": app.config["TUNE_DEFAULT_FC_CONNECTION"],
        "default_bridge_host": app.config["TUNE_DEFAULT_BRIDGE_HOST"],
        "default_usb_device": app.config["TUNE_DEFAULT_USB_DEVICE"],
        "default_pi_model": app.config["TUNE_DEFAULT_PI_MODEL"],
        "default_thinking_level": app.config["TUNE_DEFAULT_THINKING_LEVEL"],
        "pi_model_choices": PI_MODEL_CHOICES,
        "thinking_level_choices": THINKING_LEVEL_CHOICES,
    }


def _loop_iterations(conn: Any, loop_id: int) -> list[dict[str, Any]]:
    iteration_rows = conn.execute(
        "SELECT * FROM tuning_iterations WHERE loop_id = ? ORDER BY created_at DESC, id DESC",
        (loop_id,),
    ).fetchall()
    iterations = []
    for row in iteration_rows:
        item = _row_dict(row)
        diagnosis = _row_dict(conn.execute("SELECT * FROM diagnoses WHERE iteration_id = ?", (item["id"],)).fetchone())
        if diagnosis:
            diagnosis["evidence"] = json.loads(diagnosis["evidence_json"])
        item["diagnosis"] = diagnosis
        item["logs"] = _iteration_logs(conn, item["id"])
        update = _row_dict(conn.execute("SELECT * FROM tune_updates WHERE iteration_id = ?", (item["id"],)).fetchone())
        if update:
            update["settings"] = json.loads(update["settings_json"])
        item["update"] = update
        iterations.append(item)
    return iterations


def _iteration_logs(conn: Any, iteration_id: int) -> list[Any]:
    return conn.execute(
        """
        SELECT l.id, l.build_id, l.managed_path, l.parse_status, l.imported_at, il.role
        FROM iteration_logs il
        JOIN blackbox_logs l ON l.id = il.log_id
        WHERE il.iteration_id = ?
        ORDER BY l.id
        """,
        (iteration_id,),
    ).fetchall()
