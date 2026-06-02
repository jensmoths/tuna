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

from tune.services.builds import create_build
from tune.services.loops import create_loop
from tune.storage import connect, init_db
from tune.web.app import create_app
from tune.web.pi_supervisor import PiRpcSupervisor


class PiSupervisorWebTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db_path = self.root / "tune.sqlite3"
        self.conn = connect(self.db_path)
        init_db(self.conn)

    def tearDown(self):
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

        with patch("tune.web.pi_supervisor.subprocess.Popen", return_value=fake_process) as popen:
            response = client.post(
                f"/loops/{loop_id}/tuning-agent/start",
                data={"bridge_host": "tuna-bridge-usb"},
            )

        self.assertEqual(response.status_code, 302)
        popen.assert_called_once()
        args = popen.call_args.args[0]
        self.assertEqual(args[:3], ["pi-test", "--mode", "rpc"])
        sent = fake_process.stdin.getvalue()
        self.assertIn('"type": "get_state"', sent)
        self.assertIn('"type": "prompt"', sent)
        self.assertIn("FCS Bridge host: tuna-bridge-usb", sent)

        session = self.conn.execute("SELECT * FROM tuning_agent_sessions WHERE loop_id = ?", (loop_id,)).fetchone()
        self.assertEqual(session["status"], "Starting Tuning Agent")
        self.assertEqual(session["bridge_host"], "tuna-bridge-usb")
        self.assertEqual(session["process_id"], 1234)

        page = client.get(f"/loops/{loop_id}")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"Tuning Agent", page.data)
        self.assertIn(b"Starting Tuning Agent", page.data)

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


if __name__ == "__main__":
    unittest.main()
