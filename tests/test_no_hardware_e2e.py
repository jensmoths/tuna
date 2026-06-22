from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

try:
    import flask  # noqa: F401
except ModuleNotFoundError as exc:
    raise unittest.SkipTest("Flask is not installed") from exc

from tuna_console.web.app import create_app
from tuna_core.cli.main import main


class NoopSupervisor:
    def is_loop_running(self, _loop_id: int) -> bool:
        return False

    def notify_operator_task_resolved(self, _task_id: int) -> None:
        return None

    def notify_operator_notification_acknowledged(self, _notification_id: int) -> None:
        return None


class NoHardwareEndToEndTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = self.root / "tune.sqlite3"

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli_json(self, *args: str):
        out = StringIO()
        with redirect_stdout(out):
            code = main(["--db", str(self.db), *args, "--json"])
        self.assertEqual(code, 0, out.getvalue())
        return json.loads(out.getvalue())

    def test_loop_to_operator_approval_to_applied_update_without_hardware_or_blackbox_analysis(self):
        build = self.run_cli_json(
            "build",
            "create",
            "Bench 5 inch",
            "--fc-snapshot-json",
            '{"identity":{"fc_variant":"BTFL","board_name":"FAKEF7"},"pids":{"roll":[45,80,40]}}',
            "--operator-notes",
            "No-hardware end-to-end fixture Build",
        )
        loop = self.run_cli_json(
            "loop",
            "create",
            "--build-id",
            str(build["build_id"]),
            "--tune-goal",
            "Reduce propwash while preserving freestyle response",
        )

        app = create_app(self.db)
        app.extensions["tuna_pi_supervisor"] = NoopSupervisor()
        client = app.test_client()
        workbench = client.get("/workbench")
        self.assertEqual(workbench.status_code, 302)
        self.assertEqual(workbench.headers["Location"], f"/loops/{loop['loop_id']}/workbench")

        capture_task = self.run_cli_json(
            "task",
            "request-flight-capture",
            "--build-id",
            str(build["build_id"]),
            "--loop-id",
            str(loop["loop_id"]),
            "--capture-goal",
            "Fly propwash-inducing turns for fixture evidence",
        )
        task_page = client.get(f"/loops/{loop['loop_id']}/workbench")
        self.assertEqual(task_page.status_code, 200)
        self.assertIn(b"Capture follow-up Blackbox Log", task_page.data)

        response = client.post(
            f"/tasks/{capture_task['task_id']}/resolve-flight-capture",
            data={
                "decision": "captured_needs_transfer",
                "notes": "Fixture capture complete; Tuning Agent may import retained Blackbox Log.",
                "next": f"/loops/{loop['loop_id']}/workbench",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], f"/loops/{loop['loop_id']}/workbench")

        imported = self.run_cli_json(
            "log",
            "import",
            "reference-logs/btfl_001.bbl",
            "--build-id",
            str(build["build_id"]),
            "--loop-id",
            str(loop["loop_id"]),
            "--storage-dir",
            str(self.root / "managed-logs"),
        )
        analysis = self.run_cli_json(
            "analysis",
            "record-fixture",
            "--log-id",
            str(imported["log_id"]),
            "--scenario",
            "propwash",
        )
        self.assertEqual(analysis["row_count"], 4200)
        self.assertEqual(analysis["scenario"], "propwash")
        summary = self.run_cli_json("analysis", "summary", "--log-id", str(imported["log_id"]))
        self.assertTrue(summary["quality"]["usable"])
        self.assertEqual(summary["pid_term_analysis"]["axes"]["roll"]["samples"], 4200)
        self.assertEqual(summary["propwash_analysis"]["summary"]["segment_count"], 2)

        iteration = self.run_cli_json(
            "iteration",
            "create",
            "--loop-id",
            str(loop["loop_id"]),
            "--log-id",
            str(imported["log_id"]),
        )
        diagnosis = self.run_cli_json(
            "diagnosis",
            "record",
            "--iteration-id",
            str(iteration["iteration_id"]),
            "--body",
            "Fixture evidence supports a small absolute D increase for propwash control.",
            "--confidence",
            "medium",
            "--evidence-json",
            json.dumps({"log_id": imported["log_id"], "analysis_id": summary["analysis_id"]}),
        )
        update = self.run_cli_json(
            "update",
            "propose",
            "--iteration-id",
            str(iteration["iteration_id"]),
            "--build-id",
            str(build["build_id"]),
            "--settings-json",
            '{"d_roll":42}',
            "--cli-text",
            "set d_roll = 42",
        )
        review = self.run_cli_json(
            "task",
            "create",
            "--kind",
            "review_tune_update",
            "--title",
            "Review fixture Tune Update",
            "--body",
            "Review the proposed absolute Tune Update before Tuning Agent write-back.",
            "--payload-json",
            json.dumps({"tune_update_id": update["update_id"]}),
        )

        review_page = client.get(f"/loops/{loop['loop_id']}/workbench")
        self.assertEqual(review_page.status_code, 200)
        self.assertIn(b"Review fixture Tune Update", review_page.data)
        self.assertIn(b"Approve for Tuning Agent write-back", review_page.data)

        approval = client.post(
            f"/tasks/{review['task_id']}/approve-write",
            data={"safety_confirmed": "yes", "next": f"/loops/{loop['loop_id']}/workbench"},
        )
        self.assertEqual(approval.status_code, 302)
        self.assertEqual(approval.headers["Location"], f"/loops/{loop['loop_id']}/workbench")

        pending = self.run_cli_json("update", "pending-writes")
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["update_id"], update["update_id"])
        self.assertEqual(pending[0]["settings"], {"d_roll": 42})
        self.assertIn("small absolute D increase", pending[0]["diagnosis"])

        applied = self.run_cli_json("update", "apply", "--update-id", str(update["update_id"]))
        self.assertEqual(applied["status"], "applied")
        final_status = self.run_cli_json("loop", "status", "--loop-id", str(loop["loop_id"]))
        self.assertEqual(final_status["pending_writes"], 0)
        self.assertEqual(final_status["current_iteration"], {})
        decisions = {task["response"]["decision"] for task in final_status["recent_tasks"] if task.get("response")}
        self.assertIn("approved_for_write", decisions)
        self.assertTrue(final_status["usable_logs"][0]["latest_analysis"]["quality"]["usable"])


if __name__ == "__main__":
    unittest.main()
