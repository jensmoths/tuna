from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, TextIO

from tuna_console.web.agent_events import status_for_tool, trace_for_event
from tuna_console.web.agent_prompts import continue_prompt, initial_prompt
from tuna_console.web.agent_sessions import AgentSessionStore, loop_id_from_payload
from tuna_console.web.agent_trace import classify_trace_message

PI_MODEL_CHOICES = {
    "gpt-5.4-mini": "GPT-5.4 mini",
    "gpt-5.5": "GPT-5.5",
}
THINKING_LEVEL_CHOICES = {"off", "minimal", "low", "medium", "high", "xhigh"}


class PiRpcSupervisor:
    """Process supervisor for one Pi RPC **Tuning Agent** process per **Loop**.

    This class owns subprocess lifecycle and coarse status only. It does not
    decide Tuna workflow actions inside a **Loop**.
    """

    def __init__(
        self,
        db_path: str | Path,
        *,
        cwd: str | Path | None = None,
        pi_command: str = "pi",
        verbose: bool = False,
    ) -> None:
        self.db_path = Path(db_path)
        self.cwd = Path(cwd) if cwd is not None else Path.cwd()
        self.pi_command = pi_command
        self.verbose = verbose
        self._sessions = AgentSessionStore(self.db_path)
        self._lock = threading.Lock()
        self._processes: dict[int, subprocess.Popen[str]] = {}

    def start_loop(
        self,
        loop_id: int,
        *,
        bridge_host: str = "",
        fc_connection: str = "bridge",
        usb_device: str = "",
        pi_model: str = "gpt-5.4-mini",
        thinking_level: str = "medium",
        prompt_message: str | None = None,
    ) -> None:
        if pi_model not in PI_MODEL_CHOICES:
            raise ValueError(f"Unsupported Pi model: {pi_model}")
        if thinking_level not in THINKING_LEVEL_CHOICES:
            raise ValueError(f"Unsupported Pi thinking level: {thinking_level}")
        if fc_connection not in {"bridge", "usb"}:
            raise ValueError(f"Unsupported FC connection: {fc_connection}")
        loop = self._sessions.load_loop(loop_id)
        session = self.get_session(loop_id)
        args = [
            self.pi_command,
            "--mode",
            "rpc",
            "--no-context-files",
            "--no-skills",
            "--model",
            f"openai-codex/{pi_model}",
            "--thinking",
            thinking_level,
            "--name",
            f"Tuna Loop {loop_id}",
        ]
        if session and session.get("pi_session_file"):
            args.extend(["--session", session["pi_session_file"]])

        self._set_session(
            loop_id,
            status="Starting Tuning Agent",
            bridge_host=bridge_host,
            fc_connection=fc_connection,
            usb_device=usb_device,
            pi_model=pi_model,
            thinking_level=thinking_level,
            process_id=None,
            last_error=None,
        )
        self._append_debug_trace(loop_id, "starting Pi RPC Tuning Agent: " + " ".join(args))
        try:
            process = subprocess.Popen(
                args,
                cwd=self.cwd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=self._process_env(bridge_host, fc_connection=fc_connection, usb_device=usb_device),
                text=True,
                bufsize=1,
            )
        except OSError as exc:
            self._set_session(loop_id, status="Failed", last_error=str(exc))
            raise

        with self._lock:
            self._processes[loop_id] = process
        self._set_session(loop_id, status="Starting Tuning Agent", process_id=process.pid)
        self._append_debug_trace(loop_id, f"started Pi RPC process pid={process.pid}")

        if process.stdout is not None:
            threading.Thread(target=self._read_stdout, args=(loop_id, process.stdout), daemon=True).start()
        if process.stderr is not None:
            threading.Thread(target=self._read_stderr, args=(loop_id, process.stderr), daemon=True).start()

        self._send(process, {"type": "get_state"}, loop_id=loop_id)
        self._send(process, {"type": "prompt", "message": prompt_message or self._initial_prompt(loop, bridge_host, fc_connection=fc_connection, usb_device=usb_device)}, loop_id=loop_id)

    def continue_loop(
        self,
        loop_id: int,
        *,
        bridge_host: str = "",
        fc_connection: str = "bridge",
        usb_device: str = "",
        pi_model: str | None = None,
        thinking_level: str | None = None,
    ) -> None:
        session = self.get_session(loop_id) or {}
        selected_connection = fc_connection or session.get("fc_connection", "bridge") or "bridge"
        selected_bridge_host = bridge_host or session.get("bridge_host", "")
        selected_usb_device = usb_device or session.get("usb_device", "")
        selected_model = pi_model or session.get("pi_model") or "gpt-5.4-mini"
        selected_thinking = thinking_level or session.get("thinking_level") or "medium"
        self._append_debug_trace(loop_id, "continuing Pi RPC Tuning Agent session after interruption")
        prompt_message = self._continue_prompt(
            self._sessions.load_loop(loop_id),
            selected_bridge_host,
            fc_connection=selected_connection,
            usb_device=selected_usb_device,
        )
        with self._lock:
            process = self._processes.get(loop_id)
        if process is not None and process.poll() is None:
            command_type = "prompt" if session.get("status") == "Idle" else "follow_up"
            self._send(process, {"type": command_type, "message": prompt_message}, loop_id=loop_id)
            self._set_session(
                loop_id,
                status="Inspecting Tuna state",
                bridge_host=selected_bridge_host,
                fc_connection=selected_connection,
                usb_device=selected_usb_device,
                pi_model=selected_model,
                thinking_level=selected_thinking,
            )
            return
        self.start_loop(
            loop_id,
            bridge_host=selected_bridge_host,
            fc_connection=selected_connection,
            usb_device=selected_usb_device,
            pi_model=selected_model,
            thinking_level=selected_thinking,
            prompt_message=prompt_message,
        )

    def abort_loop(self, loop_id: int) -> None:
        with self._lock:
            process = self._processes.get(loop_id)
        if process is not None and process.poll() is None:
            self._send(process, {"type": "abort"}, loop_id=loop_id)
            process.terminate()
            self._append_debug_trace(loop_id, "terminated Pi RPC process")
        self._set_session(loop_id, status="Aborted", process_id=None)

    def notify_operator_task_resolved(self, task_id: int) -> None:
        task = self._sessions.load_task(task_id)
        if task is None:
            return
        loop_ids = self._sessions.loop_ids_for_task(task)
        if not loop_ids:
            loop_ids = self._active_loop_ids()
        if not loop_ids:
            print(f"[Tuna supervisor] Operator Task #{task_id} resolved, but no active Tuning Agent session was found", file=sys.stderr, flush=True)
            return
        message = (
            f"Operator Task #{task_id} ({task['kind']}) has been resolved in the Operator Console. "
            f"Inspect Tuna state with JSON tuna-core commands, read the task response with `python3 -m tuna_core task show --task-id {task_id} --json`, and continue the Loop decision process."
        )
        for loop_id in loop_ids:
            self._append_debug_trace(loop_id, f"Operator Task #{task_id} resolved; notifying Tuning Agent")
            with self._lock:
                process = self._processes.get(loop_id)
            if process is not None and process.poll() is None:
                session = self.get_session(loop_id) or {}
                command_type = "prompt" if session.get("status") == "Idle" else "follow_up"
                self._send(process, {"type": command_type, "message": message}, loop_id=loop_id)
                self._set_session(loop_id, status="Inspecting Tuna state")
            else:
                self._append_debug_trace(loop_id, "no running Pi RPC process; restarting Pi RPC session for Operator Task resolution")
                session = self.get_session(loop_id) or {}
                if not session:
                    self._append_debug_trace(loop_id, "no stored Pi RPC session to resume for Operator Task resolution")
                    continue
                try:
                    self.start_loop(
                        loop_id,
                        bridge_host=session.get("bridge_host", ""),
                        fc_connection=session.get("fc_connection", "bridge") or "bridge",
                        usb_device=session.get("usb_device", ""),
                        pi_model=session.get("pi_model") or "gpt-5.4-mini",
                        thinking_level=session.get("thinking_level") or "medium",
                    )
                except OSError as exc:
                    self._append_debug_trace(loop_id, f"failed to restart Pi RPC process for Operator Task resolution: {exc}")
                    continue
                with self._lock:
                    restarted = self._processes.get(loop_id)
                if restarted is not None and restarted.poll() is None:
                    self._send(restarted, {"type": "follow_up", "message": message}, loop_id=loop_id)
                else:
                    self._append_debug_trace(loop_id, "failed to restart Pi RPC process for Operator Task resolution")

    def notify_operator_notification_acknowledged(self, notification_id: int) -> None:
        notification = self._sessions.load_notification(notification_id)
        if notification is None:
            return
        loop_id = loop_id_from_payload(notification.get("payload_json"))
        if loop_id is None:
            return
        self._append_debug_trace(loop_id, f"Operator Notification #{notification_id} acknowledged")

    def get_session(self, loop_id: int) -> dict[str, Any] | None:
        return self._sessions.get_session(loop_id)

    def is_loop_running(self, loop_id: int) -> bool:
        with self._lock:
            process = self._processes.get(loop_id)
        return process is not None and process.poll() is None

    def _active_loop_ids(self) -> list[int]:
        with self._lock:
            return [loop_id for loop_id, process in self._processes.items() if process.poll() is None]

    def _set_session(self, loop_id: int, **updates: Any) -> None:
        self._sessions.set_session(loop_id, **updates)

    def _append_debug_trace(self, loop_id: int, message: str) -> None:
        print(self._console_trace_line(loop_id, message), file=sys.stderr, flush=True)
        self._sessions.append_debug_trace(loop_id, message)

    def _console_trace_line(self, loop_id: int, message: str) -> str:
        kind, label, text = self._classify_trace_message(message)
        prefix = f"[Tuna Loop #{loop_id}]"
        if not sys.stderr.isatty() or os.environ.get("NO_COLOR"):
            return f"{prefix} {label}: {text}"
        colors = {
            "message": "\033[94m",
            "tool": "\033[95m",
            "supervisor": "\033[92m",
            "rpc": "\033[93m",
            "error": "\033[91m",
            "log": "\033[90m",
        }
        bold = "\033[1m"
        reset = "\033[0m"
        color = colors.get(kind, colors["log"])
        return f"{bold}{prefix}{reset} {color}{label}:{reset} {text}"

    def _classify_trace_message(self, message: str) -> tuple[str, str, str]:
        kind, label, text = classify_trace_message(message)
        return kind, "PI RPC" if label == "Pi RPC" else label.upper(), text

    def _send(self, process: subprocess.Popen[str], command: dict[str, Any], *, loop_id: int | None = None) -> None:
        if process.stdin is None:
            return
        process.stdin.write(json.dumps(command) + "\n")
        process.stdin.flush()
        if loop_id is not None:
            if command.get("type") == "prompt":
                self._append_debug_trace(loop_id, "sent initial prompt to Pi RPC")
            elif command.get("type") == "follow_up":
                self._append_debug_trace(loop_id, "sent follow-up prompt to Pi RPC")
            else:
                self._append_debug_trace(loop_id, f"sent Pi RPC command: {command.get('type')}")

    def _process_env(self, bridge_host: str, *, fc_connection: str, usb_device: str) -> dict[str, str]:
        env = os.environ.copy()
        env["TUNA_DB"] = str(self.db_path)
        env["FCS_CONNECTION"] = fc_connection
        if bridge_host:
            env["FCS_BRIDGE_HOST"] = bridge_host
        if usb_device:
            env["FCS_USB_DEVICE"] = usb_device
        return env

    def _read_stdout(self, loop_id: int, stdout: TextIO) -> None:
        for raw_line in stdout:
            line = raw_line.rstrip("\r\n")
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                self._set_session(loop_id, status="Failed", last_error=f"Invalid Pi RPC JSON: {line[:200]}")
                self._append_debug_trace(loop_id, f"invalid Pi RPC JSON: {line[:200]}")
                continue
            trace = self._trace_for_event(event)
            if trace:
                self._append_debug_trace(loop_id, trace)
            self._handle_event(loop_id, event)
        with self._lock:
            process = self._processes.pop(loop_id, None)
        if process is not None:
            if process.poll() not in (0, None):
                self._set_session(loop_id, status="Failed", process_id=None)
                self._append_debug_trace(loop_id, "Pi RPC process exited with failure")
            else:
                self._set_session(loop_id, status="Idle", process_id=None)
                self._append_debug_trace(loop_id, "Pi RPC process exited")

    def _read_stderr(self, loop_id: int, stderr: TextIO) -> None:
        for raw_line in stderr:
            line = raw_line.strip()
            if line:
                self._set_session(loop_id, last_error=line[:500])
                self._append_debug_trace(loop_id, f"stderr: {line[:500]}")

    def _handle_event(self, loop_id: int, event: dict[str, Any]) -> None:
        event_type = event.get("type")
        if event_type == "response" and event.get("command") == "get_state" and event.get("success"):
            data = event.get("data") or {}
            self._set_session(
                loop_id,
                pi_session_id=data.get("sessionId"),
                pi_session_file=data.get("sessionFile"),
            )
        elif event_type == "agent_start":
            self._set_session(loop_id, status="Inspecting Tuna state")
        elif event_type == "agent_end":
            self._set_session(loop_id, status="Idle")
        elif event_type == "tool_execution_start":
            self._set_session(loop_id, status=status_for_tool(event))
        elif event_type == "extension_ui_request":
            self._set_session(loop_id, status="Waiting for Operator Task")
        elif event_type in {"extension_error", "auto_retry_end"} and event.get("success") is False:
            self._set_session(loop_id, status="Failed", last_error=str(event)[:500])

    def _trace_for_event(self, event: dict[str, Any]) -> str | None:
        return trace_for_event(event, verbose=self.verbose)

    def _initial_prompt(self, loop: dict[str, Any], bridge_host: str, *, fc_connection: str, usb_device: str) -> str:
        return initial_prompt(db_path=self.db_path, loop=loop, bridge_host=bridge_host, fc_connection=fc_connection, usb_device=usb_device)

    def _continue_prompt(self, loop: dict[str, Any], bridge_host: str, *, fc_connection: str, usb_device: str) -> str:
        return continue_prompt(db_path=self.db_path, loop=loop, bridge_host=bridge_host, fc_connection=fc_connection, usb_device=usb_device)
