from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TextIO

from tune.storage import connect, init_db

_UNSET = object()

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
        self._lock = threading.Lock()
        self._processes: dict[int, subprocess.Popen[str]] = {}

    def start_loop(
        self,
        loop_id: int,
        *,
        bridge_host: str = "",
        pi_model: str = "gpt-5.4-mini",
        thinking_level: str = "medium",
        prompt_message: str | None = None,
    ) -> None:
        if pi_model not in PI_MODEL_CHOICES:
            raise ValueError(f"Unsupported Pi model: {pi_model}")
        if thinking_level not in THINKING_LEVEL_CHOICES:
            raise ValueError(f"Unsupported Pi thinking level: {thinking_level}")
        loop = self._load_loop(loop_id)
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
        self._send(process, {"type": "prompt", "message": prompt_message or self._initial_prompt(loop, bridge_host)}, loop_id=loop_id)

    def continue_loop(
        self,
        loop_id: int,
        *,
        bridge_host: str = "",
        pi_model: str | None = None,
        thinking_level: str | None = None,
    ) -> None:
        session = self.get_session(loop_id) or {}
        selected_bridge_host = bridge_host or session.get("bridge_host", "")
        selected_model = pi_model or session.get("pi_model") or "gpt-5.4-mini"
        selected_thinking = thinking_level or session.get("thinking_level") or "medium"
        self._append_debug_trace(loop_id, "continuing Pi RPC Tuning Agent session after interruption")
        self.start_loop(
            loop_id,
            bridge_host=selected_bridge_host,
            pi_model=selected_model,
            thinking_level=selected_thinking,
            prompt_message=self._continue_prompt(self._load_loop(loop_id), selected_bridge_host),
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
        task = self._load_task(task_id)
        if task is None:
            return
        loop_ids = self._loop_ids_for_task(task)
        if not loop_ids:
            loop_ids = self._active_loop_ids()
        if not loop_ids:
            print(f"[Tuna supervisor] Operator Task #{task_id} resolved, but no active Tuning Agent session was found", file=sys.stderr, flush=True)
            return
        message = (
            f"Operator Task #{task_id} ({task['kind']}) has been resolved in the Operator Console. "
            f"Inspect Tuna state with JSON tune commands, read the task response with `python3 -m tune --db {self.db_path} task show --task-id {task_id} --json`, and continue the Loop decision process."
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
                self.start_loop(
                    loop_id,
                    bridge_host=session.get("bridge_host", ""),
                    pi_model=session.get("pi_model") or "gpt-5.4-mini",
                    thinking_level=session.get("thinking_level") or "medium",
                )
                with self._lock:
                    restarted = self._processes.get(loop_id)
                if restarted is not None and restarted.poll() is None:
                    self._send(restarted, {"type": "follow_up", "message": message}, loop_id=loop_id)
                else:
                    self._append_debug_trace(loop_id, "failed to restart Pi RPC process for Operator Task resolution")

    def notify_operator_notification_acknowledged(self, notification_id: int) -> None:
        notification = self._load_notification(notification_id)
        if notification is None:
            return
        loop_id = self._loop_id_from_payload(notification.get("payload_json"))
        if loop_id is None:
            return
        self._append_debug_trace(loop_id, f"Operator Notification #{notification_id} acknowledged")

    def get_session(self, loop_id: int) -> dict[str, Any] | None:
        try:
            conn = connect(self.db_path)
        except sqlite3.Error:
            return
        init_db(conn)
        row = conn.execute("SELECT * FROM tuning_agent_sessions WHERE loop_id = ?", (loop_id,)).fetchone()
        conn.close()
        return dict(row) if row else None

    def is_loop_running(self, loop_id: int) -> bool:
        with self._lock:
            process = self._processes.get(loop_id)
        return process is not None and process.poll() is None

    def _load_loop(self, loop_id: int) -> dict[str, Any]:
        conn = connect(self.db_path)
        init_db(conn)
        row = conn.execute(
            """
            SELECT l.*, b.name AS build_name, b.fc_snapshot_json, b.operator_notes
            FROM loops l
            JOIN builds b ON b.id = l.build_id
            WHERE l.id = ?
            """,
            (loop_id,),
        ).fetchone()
        conn.close()
        if row is None:
            raise ValueError(f"Loop not found: {loop_id}")
        return dict(row)

    def _load_task(self, task_id: int) -> dict[str, Any] | None:
        conn = connect(self.db_path)
        init_db(conn)
        row = conn.execute("SELECT * FROM operator_tasks WHERE id = ?", (task_id,)).fetchone()
        conn.close()
        return dict(row) if row else None

    def _load_notification(self, notification_id: int) -> dict[str, Any] | None:
        conn = connect(self.db_path)
        init_db(conn)
        row = conn.execute("SELECT * FROM operator_notifications WHERE id = ?", (notification_id,)).fetchone()
        conn.close()
        return dict(row) if row else None

    def _active_loop_ids(self) -> list[int]:
        with self._lock:
            return [loop_id for loop_id, process in self._processes.items() if process.poll() is None]

    def _loop_ids_for_task(self, task: dict[str, Any]) -> list[int]:
        loop_id = self._loop_id_from_payload(task.get("payload_json"))
        if loop_id is not None:
            return [loop_id]
        try:
            payload = json.loads(task.get("payload_json") or "{}")
        except json.JSONDecodeError:
            payload = {}
        update_id = payload.get("tune_update_id")
        if update_id is None:
            return []
        conn = connect(self.db_path)
        init_db(conn)
        row = conn.execute(
            """
            SELECT i.loop_id
            FROM tune_updates u
            JOIN tuning_iterations i ON i.id = u.iteration_id
            WHERE u.id = ?
            """,
            (int(update_id),),
        ).fetchone()
        conn.close()
        return [int(row["loop_id"])] if row else []

    def _loop_id_from_payload(self, payload_json: str | None) -> int | None:
        try:
            payload = json.loads(payload_json or "{}")
        except json.JSONDecodeError:
            return None
        loop_id = payload.get("loop_id")
        return int(loop_id) if loop_id is not None else None

    def _set_session(
        self,
        loop_id: int,
        *,
        status: str | object = _UNSET,
        bridge_host: str | object = _UNSET,
        process_id: int | None | object = _UNSET,
        last_error: str | None | object = _UNSET,
        pi_session_id: str | object = _UNSET,
        pi_session_file: str | object = _UNSET,
        pi_model: str | object = _UNSET,
        thinking_level: str | object = _UNSET,
    ) -> None:
        try:
            conn = connect(self.db_path)
        except sqlite3.Error:
            return
        init_db(conn)
        conn.execute(
            "INSERT OR IGNORE INTO tuning_agent_sessions (loop_id, started_at) VALUES (?, CURRENT_TIMESTAMP)",
            (loop_id,),
        )
        updates: list[str] = []
        params: list[Any] = []
        for column, value in (
            ("status", status),
            ("bridge_host", bridge_host),
            ("process_id", process_id),
            ("last_error", last_error),
            ("pi_session_id", pi_session_id),
            ("pi_session_file", pi_session_file),
            ("pi_model", pi_model),
            ("thinking_level", thinking_level),
        ):
            if value is not _UNSET:
                updates.append(f"{column} = ?")
                params.append(value)
        if updates:
            updates.append("updated_at = CURRENT_TIMESTAMP")
            params.append(loop_id)
            conn.execute(f"UPDATE tuning_agent_sessions SET {', '.join(updates)} WHERE loop_id = ?", params)
        conn.commit()
        conn.close()

    def _append_debug_trace(self, loop_id: int, message: str) -> None:
        timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        line = f"[{timestamp}] {message}"
        print(self._console_trace_line(loop_id, message), file=sys.stderr, flush=True)
        try:
            conn = connect(self.db_path)
        except sqlite3.Error:
            return
        init_db(conn)
        row = conn.execute("SELECT debug_trace FROM tuning_agent_sessions WHERE loop_id = ?", (loop_id,)).fetchone()
        existing = row["debug_trace"] if row else ""
        trace = (existing + "\n" + line).strip()[-8000:]
        conn.execute(
            "UPDATE tuning_agent_sessions SET debug_trace = ?, updated_at = CURRENT_TIMESTAMP WHERE loop_id = ?",
            (trace, loop_id),
        )
        conn.commit()
        conn.close()

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
        if message.startswith("Tuning Agent message: "):
            return "message", "MESSAGE", message.removeprefix("Tuning Agent message: ")
        if message.startswith("tool start:") or message.startswith("tool end:"):
            return "tool", "TOOL", message
        if "error" in message.lower() or "failed" in message.lower() or message.startswith("stderr:"):
            return "error", "ERROR", message
        if message.startswith(("sent ", "starting ", "started ", "continuing ", "Operator Task", "Operator Notification", "no running", "terminated ")):
            return "supervisor", "SUPERVISOR", message
        if message.startswith("Pi RPC") or message.startswith("agent ") or message.startswith("Tuning Agent requested"):
            return "rpc", "PI RPC", message
        return "log", "LOG", message

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
            self._set_session(loop_id, status=self._status_for_tool(event))
        elif event_type == "extension_ui_request":
            self._set_session(loop_id, status="Waiting for Operator Task")
        elif event_type in {"extension_error", "auto_retry_end"} and event.get("success") is False:
            self._set_session(loop_id, status="Failed", last_error=str(event)[:500])

    def _status_for_tool(self, event: dict[str, Any]) -> str:
        args = event.get("args") or {}
        text = " ".join(str(value) for value in args.values()).lower()
        if "blackbox transfer" in text or "msc_raw" in text:
            return "Transferring Blackbox Log"
        if " log import" in text:
            return "Importing Blackbox Log"
        if " analysis decode" in text or " decode-analyze" in text:
            return "Decoding Blackbox Log"
        if " analysis analyze" in text:
            return "Analyzing Blackbox Log"
        if " diagnosis record" in text:
            return "Recording Diagnosis"
        if " pending-writes" in text or " update apply" in text or "record-write-failure" in text:
            return "Writing approved Tune Update through FCS"
        if " task" in text:
            return "Waiting for Operator Task"
        if " loop" in text:
            return "Creating or resuming Loop"
        if " build" in text:
            return "Confirming Build"
        return "Inspecting Tuna state"

    def _trace_for_event(self, event: dict[str, Any]) -> str | None:
        event_type = str(event.get("type") or "event")
        if event_type == "message_update":
            return None
        if event_type == "tool_execution_update" and not self.verbose:
            return None
        if event_type == "message_start":
            return None
        if event_type == "message_end":
            text = self._message_text(event.get("message"))
            if text:
                return f"Tuning Agent message: {text[:1000]}"
            return "Tuning Agent message completed"
        if event_type == "tool_execution_start":
            args = event.get("args") or {}
            command = " ".join(str(value) for value in args.values())[:500]
            return f"tool start: {command}"
        if event_type == "tool_execution_end":
            success = event.get("success")
            return f"tool end: success={success}"
        if event_type == "agent_start":
            return "agent started responding"
        if event_type == "agent_end":
            return "agent finished responding"
        if event_type == "extension_ui_request":
            return "Tuning Agent requested Operator input"
        if event_type == "response":
            return f"Pi RPC response: command={event.get('command')} success={event.get('success')}"
        if event_type in {"extension_error", "auto_retry_end"}:
            return f"{event_type}: success={event.get('success')}"
        return f"Pi RPC event: {event_type}"

    def _message_text(self, message: Any) -> str:
        if not isinstance(message, dict):
            return ""
        content = message.get("content")
        if isinstance(content, str):
            return content.strip()
        if not isinstance(content, list):
            return ""
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str):
                parts.append(item["text"].strip())
        return "\n".join(part for part in parts if part)

    def _initial_prompt(self, loop: dict[str, Any], bridge_host: str) -> str:
        bridge_line = bridge_host or "not provided"
        skill_text = self._tuning_agent_skill_text()
        fcs_step = (
            f"2. If an FCS Bridge host is provided, query the connected FC with `PYTHONPATH=fcs-host python3 fcs-host/fcs.py inspect --bridge-host {bridge_host} --json` and compare that snapshot with the Loop Build snapshot."
            if bridge_host
            else "2. No FCS Bridge host was provided; skip connected-FC inspection unless one appears in Tuna state."
        )
        return f"""Act as the Tuna Tuning Agent for this Loop. Use the injected operating instructions below; do not load skills, context files, source files, or repository documentation during normal Loop operation.

Injected Tuna Tuning Agent operating instructions:
{skill_text}

Runtime Loop assignment:

Operator requested work on an existing Loop.

Database: {self.db_path}
Loop: {loop['id']}
Build: {loop['build_id']} ({loop['build_name']})
Tune Goal: {loop['tune_goal']}
FCS Bridge host: {bridge_line}

First:
1. Inspect compact Tuna state with `python3 -m tune --db {self.db_path} loop status --loop-id {loop['id']} --json`.
{fcs_step}
3. If FCS inspection fails, create a `request_fcs_connection` Operator Task. Only create a `confirm_build` Operator Task when a real FCS-derived FC snapshot is available and is missing, ambiguous, or does not clearly match the Loop Build.
4. Confirm whether the Build and Tune Goal are sufficient.
5. If needed, create Operator Tasks.
6. Create or resume the Loop context in this Pi session.
7. Do not start a Tuning Iteration until suitable imported Blackbox Logs are selected.

Preserve Tuna safety rules. Do not apply a Tune Update without Operator review.
Use FCS, not raw Bridge protocol access, for flight-controller operations.
Use CLI help or Tuna commands if syntax is unclear; do not read source code or repository docs during normal Loop operation.
"""

    def _continue_prompt(self, loop: dict[str, Any], bridge_host: str) -> str:
        bridge_line = bridge_host or "not provided"
        skill_text = self._tuning_agent_skill_text()
        return f"""Continue acting as the Tuna Tuning Agent for this existing Loop after an interruption or abort. Use the injected operating instructions below; do not load skills, context files, source files, or repository documentation during normal Loop operation.

Injected Tuna Tuning Agent operating instructions:
{skill_text}

Runtime Loop assignment:

Database: {self.db_path}
Loop: {loop['id']}
Build: {loop['build_id']} ({loop['build_name']})
Tune Goal: {loop['tune_goal']}
FCS Bridge host: {bridge_line}

First:
1. Inspect compact Tuna state with `python3 -m tune --db {self.db_path} loop status --loop-id {loop['id']} --json`.
2. Check open and recently resolved Operator Tasks and Operator Notifications. If this continuation followed an Operator Task resolution, read that task with `task show --task-id <id> --json`.
3. Resume the Loop decision process from durable Tuna state and the existing Pi session history.
4. If a previous action was interrupted, verify state before retrying it.

Preserve Tuna safety rules. Do not apply a Tune Update without Operator review.
Use FCS, not raw Bridge protocol access, for flight-controller operations.
Use CLI help or Tuna commands if syntax is unclear; do not read source code or repository docs during normal Loop operation.
"""

    def _tuning_agent_skill_text(self) -> str:
        skill_path = Path(__file__).resolve().parents[1] / "agent" / "SKILL.md"
        return skill_path.read_text(encoding="utf-8").strip()
