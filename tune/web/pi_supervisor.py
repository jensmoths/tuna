from __future__ import annotations

import json
import subprocess
import threading
from pathlib import Path
from typing import Any, TextIO

from tune.storage import connect, init_db

_UNSET = object()


class PiRpcSupervisor:
    """Process supervisor for one Pi RPC **Tuning Agent** process per **Loop**.

    This class owns subprocess lifecycle and coarse status only. It does not
    decide Tuna workflow actions inside a **Loop**.
    """

    def __init__(self, db_path: str | Path, *, cwd: str | Path | None = None, pi_command: str = "pi") -> None:
        self.db_path = Path(db_path)
        self.cwd = Path(cwd) if cwd is not None else Path.cwd()
        self.pi_command = pi_command
        self._lock = threading.Lock()
        self._processes: dict[int, subprocess.Popen[str]] = {}

    def start_loop(self, loop_id: int, *, bridge_host: str = "") -> None:
        loop = self._load_loop(loop_id)
        session = self.get_session(loop_id)
        args = [self.pi_command, "--mode", "rpc", "--name", f"Tuna Loop {loop_id}"]
        if session and session.get("pi_session_file"):
            args.extend(["--session", session["pi_session_file"]])

        self._set_session(
            loop_id,
            status="Starting Tuning Agent",
            bridge_host=bridge_host,
            process_id=None,
            last_error=None,
        )
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

        if process.stdout is not None:
            threading.Thread(target=self._read_stdout, args=(loop_id, process.stdout), daemon=True).start()
        if process.stderr is not None:
            threading.Thread(target=self._read_stderr, args=(loop_id, process.stderr), daemon=True).start()

        self._send(process, {"type": "get_state"})
        self._send(process, {"type": "prompt", "message": self._initial_prompt(loop, bridge_host)})

    def abort_loop(self, loop_id: int) -> None:
        with self._lock:
            process = self._processes.get(loop_id)
        if process is not None and process.poll() is None:
            self._send(process, {"type": "abort"})
            process.terminate()
        self._set_session(loop_id, status="Aborted", process_id=None)

    def get_session(self, loop_id: int) -> dict[str, Any] | None:
        conn = connect(self.db_path)
        init_db(conn)
        row = conn.execute("SELECT * FROM tuning_agent_sessions WHERE loop_id = ?", (loop_id,)).fetchone()
        conn.close()
        return dict(row) if row else None

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
    ) -> None:
        conn = connect(self.db_path)
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

    def _send(self, process: subprocess.Popen[str], command: dict[str, Any]) -> None:
        if process.stdin is None:
            return
        process.stdin.write(json.dumps(command) + "\n")
        process.stdin.flush()

    def _read_stdout(self, loop_id: int, stdout: TextIO) -> None:
        for raw_line in stdout:
            line = raw_line.rstrip("\r\n")
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                self._set_session(loop_id, status="Failed", last_error=f"Invalid Pi RPC JSON: {line[:200]}")
                continue
            self._handle_event(loop_id, event)
        with self._lock:
            process = self._processes.pop(loop_id, None)
        if process is not None:
            if process.poll() not in (0, None):
                self._set_session(loop_id, status="Failed", process_id=None)
            else:
                self._set_session(loop_id, status="Idle", process_id=None)

    def _read_stderr(self, loop_id: int, stderr: TextIO) -> None:
        for raw_line in stderr:
            line = raw_line.strip()
            if line:
                self._set_session(loop_id, last_error=line[:500])

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
        if " log transfer" in text or "blackbox_download" in text or "msc_raw" in text:
            return "Transferring Blackbox Log"
        if " log import" in text:
            return "Importing Blackbox Log"
        if " log decode" in text:
            return "Decoding Blackbox Log"
        if " log analyze" in text:
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

    def _initial_prompt(self, loop: dict[str, Any], bridge_host: str) -> str:
        bridge_line = bridge_host or "not provided"
        return f"""Use tune/agent/SKILL.md and act as the Tuna Tuning Agent.

Operator requested work on an existing Loop.

Database: {self.db_path}
Loop: {loop['id']}
Build: {loop['build_id']} ({loop['build_name']})
Tune Goal: {loop['tune_goal']}
FCS Bridge host: {bridge_line}

First:
1. Inspect Tuna state with JSON tune commands.
2. Confirm whether the Build and Tune Goal are sufficient.
3. If needed, create Operator Tasks.
4. Create or resume the Loop context in this Pi session.
5. Do not start a Tuning Iteration until suitable imported Blackbox Logs are selected.

Preserve Tuna safety rules. Do not apply a Tune Update without Operator review.
Use FCS, not raw Bridge protocol access, for flight-controller operations.
"""
