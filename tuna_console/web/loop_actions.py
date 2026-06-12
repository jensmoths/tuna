from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from flask import Flask, request

from tuna_core.services.loops import close_loop
from tuna_console.web.pi_supervisor import PI_MODEL_CHOICES, THINKING_LEVEL_CHOICES, PiRpcSupervisor


@dataclass(frozen=True)
class AgentLaunchOptions:
    fc_connection: str
    bridge_host: str
    usb_device: str
    pi_model: str
    thinking_level: str


def _agent_launch_options(app: Flask) -> tuple[AgentLaunchOptions, tuple[str, int] | None]:
    options = AgentLaunchOptions(
        fc_connection=request.form.get("fc_connection", "").strip() or app.config["TUNE_DEFAULT_FC_CONNECTION"],
        bridge_host=request.form.get("bridge_host", "").strip() or app.config["TUNE_DEFAULT_BRIDGE_HOST"],
        usb_device=request.form.get("usb_device", "").strip() or app.config["TUNE_DEFAULT_USB_DEVICE"],
        pi_model=request.form.get("pi_model", "").strip() or app.config["TUNE_DEFAULT_PI_MODEL"],
        thinking_level=request.form.get("thinking_level", "").strip() or app.config["TUNE_DEFAULT_THINKING_LEVEL"],
    )
    if options.fc_connection not in {"bridge", "usb"}:
        return options, ("Unsupported FC connection", 400)
    if options.pi_model not in PI_MODEL_CHOICES:
        return options, ("Unsupported Pi model", 400)
    if options.thinking_level not in THINKING_LEVEL_CHOICES:
        return options, ("Unsupported Pi thinking level", 400)
    return options, None


def _loop_exists(conn: Any, loop_id: int) -> bool:
    return conn.execute("SELECT id FROM loops WHERE id = ?", (loop_id,)).fetchone() is not None


def _start_or_continue_agent(
    app: Flask,
    loop_id: int,
    *,
    db: Callable[[], Any],
    supervisor: Callable[[], PiRpcSupervisor],
    redirect_after_form: Callable[..., Any],
    continue_existing: bool,
) -> Any:
    conn = db()
    if not _loop_exists(conn, loop_id):
        return "Loop not found", 404
    options, error = _agent_launch_options(app)
    if error:
        return error
    method = supervisor().continue_loop if continue_existing else supervisor().start_loop
    method(
        loop_id,
        bridge_host=options.bridge_host,
        fc_connection=options.fc_connection,
        usb_device=options.usb_device,
        pi_model=options.pi_model,
        thinking_level=options.thinking_level,
    )
    return redirect_after_form("loop_detail", loop_id=loop_id)


def register_loop_action_routes(
    app: Flask,
    *,
    db: Callable[[], Any],
    supervisor: Callable[[], PiRpcSupervisor],
    redirect_after_form: Callable[..., Any],
) -> None:
    @app.post("/loops/<int:loop_id>/tuning-agent/start")
    def start_tuning_agent(loop_id: int):
        return _start_or_continue_agent(
            app,
            loop_id,
            db=db,
            supervisor=supervisor,
            redirect_after_form=redirect_after_form,
            continue_existing=False,
        )

    @app.post("/loops/<int:loop_id>/tuning-agent/continue")
    def continue_tuning_agent(loop_id: int):
        return _start_or_continue_agent(
            app,
            loop_id,
            db=db,
            supervisor=supervisor,
            redirect_after_form=redirect_after_form,
            continue_existing=True,
        )

    @app.post("/loops/<int:loop_id>/tuning-agent/abort")
    def abort_tuning_agent(loop_id: int):
        supervisor().abort_loop(loop_id)
        return redirect_after_form("loop_detail", loop_id=loop_id)

    @app.post("/loops/<int:loop_id>/close")
    def close_loop_from_web(loop_id: int):
        conn = db()
        try:
            close_loop(conn, loop_id)
        except ValueError:
            return "Loop not found", 404
        from flask import redirect, url_for

        return redirect(url_for("loops"))

