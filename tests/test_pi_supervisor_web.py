from __future__ import annotations

import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch

try:
    import flask  # noqa: F401
except ModuleNotFoundError as exc:
    raise unittest.SkipTest("Flask is not installed") from exc

from tuna_core.services.builds import create_build
from tuna_core.services.loops import create_loop
from tuna_core.services.operator_tasks import create_flight_capture_task
from tuna_core.storage import connect, init_db
from tuna_console.web.app import create_app
from tuna_console.web.pi_supervisor import PiRpcSupervisor


class PiSupervisorWebTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db_path = self.root / "tune.sqlite3"
        self.conn = connect(self.db_path)
        init_db(self.conn)

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_loop_page_starts_pi_rpc_tuning_agent(self):
        build_id = create_build(self.conn, "5 inch", fc_snapshot={"fc_variant": "BTFL"})
        loop_id = create_loop(self.conn, build_id, "reduce propwash")

        class FakeProcess:
            pid = 1234

            def __init__(self):
                self.stdin = StringIO()
                self.stdout = None
                self.stderr = None

            def poll(self):
                return None

        fake_process = FakeProcess()
        app = create_app(self.db_path)
        app.config["TUNE_PI_COMMAND"] = "pi-test"
        app.config["TUNE_WORKDIR"] = str(self.root)
        client = app.test_client()

        with patch("tuna_console.web.pi_supervisor.subprocess.Popen", return_value=fake_process) as popen:
            response = client.post(
                f"/loops/{loop_id}/tuning-agent/start",
                data={"bridge_host": "tuna-bridge-usb"},
            )

        self.assertEqual(response.status_code, 302)
        popen.assert_called_once()
        args = popen.call_args.args[0]
        self.assertEqual(args[:3], ["pi-test", "--mode", "rpc"])
        self.assertIn("--no-context-files", args)
        env = popen.call_args.kwargs["env"]
        self.assertEqual(env["TUNA_DB"], str(self.db_path))
        self.assertEqual(env["FCS_BRIDGE_HOST"], "tuna-bridge-usb")
        self.assertIn("--no-skills", args)
        self.assertIn("--model", args)
        self.assertIn("openai-codex/gpt-5.4-mini", args)
        self.assertIn("--thinking", args)
        self.assertIn("medium", args)
        sent = fake_process.stdin.getvalue()
        self.assertIn('"type": "get_state"', sent)
        self.assertIn('"type": "prompt"', sent)
        self.assertIn("FCS Bridge host: tuna-bridge-usb", sent)
        self.assertIn("loop status", sent)
        self.assertIn("python3 -m tuna_fcs.cli inspect", sent)
        self.assertIn("do not read source code or repository docs", sent)
        self.assertIn("Injected Tuna Tuning Agent operating instructions", sent)
        self.assertIn("# Tuna Tuning Agent", sent)
        self.assertNotIn("Use skills/tuna-agent/SKILL.md", sent)
        self.assertNotIn("docs/domain-model.md", sent)
        self.assertIn("confirm_build", sent)

        session = self.conn.execute("SELECT * FROM tuning_agent_sessions WHERE loop_id = ?", (loop_id,)).fetchone()
        self.assertEqual(session["status"], "Starting Tuning Agent")
        self.assertEqual(session["bridge_host"], "tuna-bridge-usb")
        self.assertEqual(session["pi_model"], "gpt-5.4-mini")
        self.assertEqual(session["thinking_level"], "medium")
        self.assertEqual(session["process_id"], 1234)
        self.assertIn("starting Pi RPC Tuning Agent", session["debug_trace"])
        self.assertIn("sent initial prompt to Pi RPC", session["debug_trace"])

        page = client.get(f"/loops/{loop_id}")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"Tuning Agent", page.data)
        self.assertIn(b"Starting Tuning Agent", page.data)
        self.assertIn(b"Supervisor trace", page.data)
        self.assertIn(b"trace-supervisor", page.data)
        self.assertIn(b"sent initial prompt to Pi RPC", page.data)

    def test_loop_page_defaults_bridge_host(self):
        build_id = create_build(self.conn, "5 inch", fc_snapshot={"fc_variant": "BTFL"})
        loop_id = create_loop(self.conn, build_id, "baseline")

        class FakeProcess:
            pid = 1234

            def __init__(self):
                self.stdin = StringIO()
                self.stdout = None
                self.stderr = None

            def poll(self):
                return None

        fake_process = FakeProcess()
        app = create_app(self.db_path)
        client = app.test_client()

        page = client.get(f"/loops/{loop_id}")
        self.assertIn(b'value="tuna-bridge-usb"', page.data)
        self.assertIn(b'value="gpt-5.4-mini" selected', page.data)
        self.assertIn(b'value="gpt-5.5"', page.data)
        self.assertIn(b'value="medium" selected', page.data)

        with patch("tuna_console.web.pi_supervisor.subprocess.Popen", return_value=fake_process) as popen:
            response = client.post(
                f"/loops/{loop_id}/tuning-agent/start",
                data={"bridge_host": "", "pi_model": "gpt-5.5", "thinking_level": "xhigh"},
            )

        self.assertEqual(response.status_code, 302)
        args = popen.call_args.args[0]
        self.assertIn("openai-codex/gpt-5.5", args)
        self.assertIn("xhigh", args)
        sent = fake_process.stdin.getvalue()
        self.assertIn("FCS Bridge host: tuna-bridge-usb", sent)
        session = self.conn.execute("SELECT bridge_host, pi_model, thinking_level FROM tuning_agent_sessions WHERE loop_id = ?", (loop_id,)).fetchone()
        self.assertEqual(session["bridge_host"], "tuna-bridge-usb")
        self.assertEqual(session["pi_model"], "gpt-5.5")
        self.assertEqual(session["thinking_level"], "xhigh")

    def test_loop_page_rejects_unsupported_pi_model_options(self):
        build_id = create_build(self.conn, "5 inch")
        loop_id = create_loop(self.conn, build_id, "baseline")
        client = create_app(self.db_path).test_client()

        response = client.post(
            f"/loops/{loop_id}/tuning-agent/start",
            data={"pi_model": "gpt-4o", "thinking_level": "medium"},
        )
        self.assertEqual(response.status_code, 400)

        response = client.post(
            f"/loops/{loop_id}/tuning-agent/start",
            data={"pi_model": "gpt-5.4-mini", "thinking_level": "maximum"},
        )
        self.assertEqual(response.status_code, 400)

    def test_loop_page_aborts_pi_rpc_tuning_agent(self):
        build_id = create_build(self.conn, "5 inch")
        loop_id = create_loop(self.conn, build_id, "baseline")

        class FakeProcess:
            def __init__(self):
                self.stdin = StringIO()
                self.stdout = StringIO()
                self.stderr = StringIO()
                self.terminated = False

            def poll(self):
                return None

            def terminate(self):
                self.terminated = True

        fake_process = FakeProcess()
        app = create_app(self.db_path)
        supervisor = app.extensions.setdefault("tuna_pi_supervisor", PiRpcSupervisor(self.db_path, cwd=self.root))
        supervisor._processes[loop_id] = fake_process
        client = app.test_client()

        response = client.post(f"/loops/{loop_id}/tuning-agent/abort")

        self.assertEqual(response.status_code, 302)
        self.assertTrue(fake_process.terminated)
        self.assertIn('"type": "abort"', fake_process.stdin.getvalue())
        session = self.conn.execute("SELECT status, process_id FROM tuning_agent_sessions WHERE loop_id = ?", (loop_id,)).fetchone()
        self.assertEqual(session["status"], "Aborted")
        self.assertIsNone(session["process_id"])

    def test_loop_page_continues_aborted_pi_rpc_tuning_agent(self):
        build_id = create_build(self.conn, "5 inch")
        loop_id = create_loop(self.conn, build_id, "baseline")

        class FakeProcess:
            pid = 5678

            def __init__(self):
                self.stdin = StringIO()
                self.stdout = None
                self.stderr = None

            def poll(self):
                return None

        fake_process = FakeProcess()
        app = create_app(self.db_path)
        supervisor = app.extensions.setdefault("tuna_pi_supervisor", PiRpcSupervisor(self.db_path, cwd=self.root))
        supervisor._set_session(
            loop_id,
            status="Aborted",
            bridge_host="tuna-bridge-usb",
            pi_model="gpt-5.5",
            thinking_level="high",
            process_id=None,
            pi_session_file="saved-pi-session.jsonl",
        )
        client = app.test_client()

        page = client.get(f"/loops/{loop_id}")
        self.assertIn(b"Resume / continue after abort", page.data)

        with patch("tuna_console.web.pi_supervisor.subprocess.Popen", return_value=fake_process) as popen:
            response = client.post(
                f"/loops/{loop_id}/tuning-agent/continue",
                data={"bridge_host": "tuna-bridge-usb", "pi_model": "gpt-5.5", "thinking_level": "high"},
            )

        self.assertEqual(response.status_code, 302)
        args = popen.call_args.args[0]
        self.assertIn("--session", args)
        self.assertIn("--no-context-files", args)
        self.assertIn("--no-skills", args)
        self.assertIn("saved-pi-session.jsonl", args)
        self.assertIn("openai-codex/gpt-5.5", args)
        sent = fake_process.stdin.getvalue()
        self.assertIn("Continue acting as the Tuna Tuning Agent", sent)
        self.assertIn("do not read source code or repository docs", sent)
        self.assertIn("Injected Tuna Tuning Agent operating instructions", sent)
        self.assertIn("# Tuna Tuning Agent", sent)
        self.assertNotIn("Use skills/tuna-agent/SKILL.md", sent)
        self.assertNotIn("docs/domain-model.md", sent)
        self.assertIn("Check open and recently resolved Operator Tasks", sent)
        self.assertIn("loop status", sent)
        session = self.conn.execute("SELECT status, process_id, debug_trace FROM tuning_agent_sessions WHERE loop_id = ?", (loop_id,)).fetchone()
        self.assertEqual(session["status"], "Starting Tuning Agent")
        self.assertEqual(session["process_id"], 5678)
        self.assertIn("continuing Pi RPC Tuning Agent session", session["debug_trace"])

    def test_loop_page_shows_continue_when_db_has_stale_process_id(self):
        build_id = create_build(self.conn, "5 inch")
        loop_id = create_loop(self.conn, build_id, "baseline")
        app = create_app(self.db_path)
        supervisor = app.extensions.setdefault("tuna_pi_supervisor", PiRpcSupervisor(self.db_path, cwd=self.root))
        supervisor._set_session(loop_id, status="Idle", process_id=9999, pi_session_file="saved-pi-session.jsonl")

        page = app.test_client().get(f"/loops/{loop_id}")

        self.assertIn(b"Resume / continue after abort", page.data)
        self.assertNotIn(b"Abort Tuning Agent", page.data)

    def test_loop_page_shows_pi_rpc_tool_debug_trace(self):
        build_id = create_build(self.conn, "5 inch")
        loop_id = create_loop(self.conn, build_id, "baseline")
        app = create_app(self.db_path)
        supervisor = app.extensions.setdefault("tuna_pi_supervisor", PiRpcSupervisor(self.db_path, cwd=self.root))
        supervisor._set_session(loop_id, status="Starting Tuning Agent")

        supervisor._append_debug_trace(loop_id, supervisor._trace_for_event({
            "type": "tool_execution_start",
            "args": {"cmd": "python3 -m tuna_core --db tune.sqlite3 analysis analyze --log-id 1 --json"},
        }))
        supervisor._handle_event(loop_id, {
            "type": "tool_execution_start",
            "args": {"cmd": "python3 -m tuna_core --db tune.sqlite3 analysis analyze --log-id 1 --json"},
        })

        session = self.conn.execute("SELECT status, debug_trace FROM tuning_agent_sessions WHERE loop_id = ?", (loop_id,)).fetchone()
        self.assertEqual(session["status"], "Analyzing Blackbox Log")
        self.assertIn("tool start: python3 -m tuna_core --db tune.sqlite3 analysis analyze", session["debug_trace"])

        page = app.test_client().get(f"/loops/{loop_id}")
        self.assertIn(b"Analyzing Blackbox Log", page.data)
        self.assertIn(b"trace-tool", page.data)
        self.assertIn(b"tool start: python3 -m tuna_core --db tune.sqlite3 analysis analyze", page.data)

    def test_pi_rpc_streaming_updates_are_not_logged_but_message_end_is(self):
        build_id = create_build(self.conn, "5 inch")
        loop_id = create_loop(self.conn, build_id, "baseline")
        supervisor = PiRpcSupervisor(self.db_path, cwd=self.root)
        supervisor._set_session(loop_id, status="Inspecting Tuna state")

        update_trace = supervisor._trace_for_event({
            "type": "message_update",
            "assistantMessageEvent": {"type": "text_delta", "delta": "partial"},
        })
        end_trace = supervisor._trace_for_event({
            "type": "message_end",
            "message": {"role": "assistant", "content": [{"type": "text", "text": "I resolved the Operator Task and will inspect Tuna state."}]},
        })

        self.assertIsNone(update_trace)
        self.assertEqual(end_trace, "Tuning Agent message: I resolved the Operator Task and will inspect Tuna state.")

    def test_pi_rpc_tool_execution_updates_require_verbose(self):
        supervisor = PiRpcSupervisor(self.db_path, cwd=self.root)
        event = {"type": "tool_execution_update"}

        self.assertIsNone(supervisor._trace_for_event(event))

        verbose_supervisor = PiRpcSupervisor(self.db_path, cwd=self.root, verbose=True)
        self.assertEqual(verbose_supervisor._trace_for_event(event), "Pi RPC event: tool_execution_update")

    def test_verbose_does_not_change_other_rpc_event_logging(self):
        event = {"type": "agent_start"}

        normal_supervisor = PiRpcSupervisor(self.db_path, cwd=self.root)
        verbose_supervisor = PiRpcSupervisor(self.db_path, cwd=self.root, verbose=True)

        self.assertEqual(normal_supervisor._trace_for_event(event), "agent started responding")
        self.assertEqual(verbose_supervisor._trace_for_event(event), "agent started responding")

    def test_cli_supervisor_trace_labels_messages_and_logs(self):
        supervisor = PiRpcSupervisor(self.db_path, cwd=self.root)

        message_line = supervisor._console_trace_line(4, "Tuning Agent message: Inspecting Tuna state now.")
        tool_line = supervisor._console_trace_line(4, "tool start: python3 -m tuna_core --db tune.sqlite3 status --json")
        supervisor_line = supervisor._console_trace_line(4, "sent initial prompt to Pi RPC")

        self.assertIn("[Tuna Loop #4]", message_line)
        self.assertIn("MESSAGE:", message_line)
        self.assertIn("Inspecting Tuna state now.", message_line)
        self.assertNotIn("Tuning Agent message:", message_line)
        self.assertIn("TOOL:", tool_line)
        self.assertIn("SUPERVISOR:", supervisor_line)

    def test_resolving_operator_task_notifies_idle_tuning_agent(self):
        build_id = create_build(self.conn, "5 inch")
        loop_id = create_loop(self.conn, build_id, "baseline")
        task_id = create_flight_capture_task(self.conn, build_id=build_id, loop_id=loop_id)

        class FakeProcess:
            def __init__(self):
                self.stdin = StringIO()

            def poll(self):
                return None

        app = create_app(self.db_path)
        supervisor = app.extensions.setdefault("tuna_pi_supervisor", PiRpcSupervisor(self.db_path, cwd=self.root))
        supervisor._set_session(loop_id, status="Idle", process_id=1234)
        supervisor._processes[loop_id] = FakeProcess()

        response = app.test_client().post(
            f"/tasks/{task_id}/resolve-flight-capture",
            data={"decision": "captured_needs_transfer", "notes": "Captured follow-up Blackbox Log"},
        )

        self.assertEqual(response.status_code, 302)
        sent = supervisor._processes[loop_id].stdin.getvalue()
        self.assertIn('"type": "prompt"', sent)
        self.assertIn(f"Operator Task #{task_id}", sent)
        session = self.conn.execute("SELECT status, debug_trace FROM tuning_agent_sessions WHERE loop_id = ?", (loop_id,)).fetchone()
        self.assertEqual(session["status"], "Inspecting Tuna state")
        self.assertIn("Operator Task", session["debug_trace"])
        self.assertIn("sent initial prompt", session["debug_trace"])

    def test_resolving_operator_task_restarts_stopped_tuning_agent_session(self):
        build_id = create_build(self.conn, "5 inch")
        loop_id = create_loop(self.conn, build_id, "baseline")
        task_id = create_flight_capture_task(self.conn, build_id=build_id, loop_id=loop_id)

        class FakeProcess:
            pid = 4321

            def __init__(self):
                self.stdin = StringIO()
                self.stdout = None
                self.stderr = None

            def poll(self):
                return None

        fake_process = FakeProcess()
        app = create_app(self.db_path)
        supervisor = app.extensions.setdefault("tuna_pi_supervisor", PiRpcSupervisor(self.db_path, cwd=self.root))
        supervisor._set_session(
            loop_id,
            status="Idle",
            bridge_host="tuna-bridge-usb",
            process_id=None,
            pi_session_file="saved-pi-session.jsonl",
        )

        with patch("tuna_console.web.pi_supervisor.subprocess.Popen", return_value=fake_process) as popen:
            response = app.test_client().post(
                f"/tasks/{task_id}/resolve-flight-capture",
                data={"decision": "captured_needs_transfer", "notes": "Captured follow-up Blackbox Log"},
            )

        self.assertEqual(response.status_code, 302)
        args = popen.call_args.args[0]
        self.assertIn("--session", args)
        self.assertIn("saved-pi-session.jsonl", args)
        sent = fake_process.stdin.getvalue()
        self.assertIn('"type": "prompt"', sent)
        self.assertIn('"type": "follow_up"', sent)
        session = self.conn.execute("SELECT process_id, debug_trace FROM tuning_agent_sessions WHERE loop_id = ?", (loop_id,)).fetchone()
        self.assertEqual(session["process_id"], 4321)
        self.assertIn("restarting Pi RPC session", session["debug_trace"])


if __name__ == "__main__":
    unittest.main()
