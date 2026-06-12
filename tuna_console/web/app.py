from __future__ import annotations

import os
from pathlib import Path

from flask import Flask, redirect, render_template, request, url_for
from markupsafe import Markup, escape

from tuna_core.storage import connect, init_db
from tuna_console.web.artifact_routes import register_artifact_routes
from tuna_console.web.loop_actions import register_loop_action_routes
from tuna_console.web.loop_pages import register_loop_page_routes
from tuna_console.web.operator_routes import register_operator_routes
from tuna_console.web.pi_supervisor import PiRpcSupervisor


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

    register_loop_action_routes(app, db=db, supervisor=supervisor, redirect_after_form=_redirect_after_form)
    register_operator_routes(app, db=db, supervisor=supervisor, redirect_after_form=_redirect_after_form)
    register_artifact_routes(app, db=db)
    register_loop_page_routes(app, db=db, supervisor=supervisor)

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

    return app
